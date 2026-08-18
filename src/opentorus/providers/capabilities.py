"""Provider capabilities: what a (provider, model) pair can do, and how we know.

The routing pool needs to answer "can this profile call tools / see images / run
locally?" without a network round-trip on every acquire. Three sources feed the
answer, unioned in :func:`effective_capabilities`:

* **static** — what the provider *kind* guarantees (OpenAI and Anthropic chat models
  call tools; the mock is local; Ollama streams). Ollama tool calling is deliberately
  *not* static: it depends on the pulled model, so it must be declared or probed.
* **declared** — ``capabilities:`` listed on the profile in ``models.profiles``.
* **cached probes** — results of an explicit ``opentorus doctor --capabilities
  --probe`` run, persisted in ``.opentorus/providers/capabilities.json``.

``acquire`` never probes online; only doctor does, and only when asked. The local
predicate :func:`is_local_provider` lives here (hoisted from ``usage``) because it
is a routing/egress policy predicate first and a cost predicate second.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from opentorus.config import ModelProfile
    from opentorus.providers.base import BaseProvider

logger = logging.getLogger("opentorus")

CACHE_DIRNAME = "providers"
CACHE_FILENAME = "capabilities.json"


class ProviderCapability(StrEnum):
    tool_calling = "tool_calling"
    streaming = "streaming"
    structured_output = "structured_output"
    vision = "vision"
    large_context = "large_context"
    local_only = "local_only"
    formalization_support = "formalization_support"
    json_schema = "json_schema"


# What each provider *kind* guarantees regardless of the model behind it. Anything
# model-dependent (Ollama tool calling, vision on a specific model) is absent here
# and has to be declared on the profile or confirmed by a cached probe.
STATIC_CAPABILITIES: dict[str, frozenset[ProviderCapability]] = {
    "mock": frozenset(
        {
            ProviderCapability.tool_calling,
            ProviderCapability.streaming,
            ProviderCapability.structured_output,
            ProviderCapability.local_only,
        }
    ),
    "openai": frozenset(
        {
            ProviderCapability.tool_calling,
            ProviderCapability.structured_output,
            ProviderCapability.json_schema,
            ProviderCapability.vision,
            ProviderCapability.large_context,
        }
    ),
    "anthropic": frozenset(
        {
            ProviderCapability.tool_calling,
            ProviderCapability.structured_output,
            ProviderCapability.vision,
            ProviderCapability.large_context,
        }
    ),
    "ollama": frozenset({ProviderCapability.streaming, ProviderCapability.local_only}),
}

# Environment variable that must be set for a provider kind to work (names only —
# doctor prints these names, never their values).
CREDENTIAL_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def is_local_base_url(base_url: str | None) -> bool:
    """True when an OpenAI-compatible endpoint is a loopback/private host (no API cost).

    Running an OpenAI-compatible server locally (llama.cpp, vLLM, LM Studio, Ollama's
    OpenAI shim, …) incurs no per-token cloud cost, so cost should read ``$0 (local)``
    rather than ``$? (price unknown)`` just because the model name is not in the price
    table.
    """
    if not base_url:
        return False
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".local"):
        return True
    # RFC 1918 private ranges (a LAN inference box is still not a cloud API).
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    return False


def is_local_provider(provider: str, base_url: str | None = None) -> bool:
    """A local provider genuinely costs nothing and sends nothing off-machine: mock or
    ollama, or any provider whose ``base_url`` points at a loopback/private host (a
    local OpenAI-compatible server)."""
    return provider.lower() in {"mock", "ollama"} or is_local_base_url(base_url)


def profile_is_local(profile: ModelProfile) -> bool:
    """Local-vs-cloud classification of a profile, honouring its explicit override."""
    if profile.local_only is not None:
        return profile.local_only
    return is_local_provider(profile.provider, profile.base_url)


class CapabilityRecord(BaseModel):
    """One cached capability observation for a (provider, model, base_url) triple."""

    provider: str
    model: str
    base_url: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    source: Literal["static", "declared", "probe"] = "probe"
    probed_at: datetime | None = None
    # Human-readable probe outcome (e.g. why tool calling stayed unconfirmed).
    note: str | None = None


def cache_key(provider: str, model: str, base_url: str | None) -> str:
    return f"{provider.lower()}|{model}|{base_url or ''}"


def default_cache_path(ot_dir: Path) -> Path:
    return ot_dir / CACHE_DIRNAME / CACHE_FILENAME


class CapabilityCache:
    """Atomic JSON cache of probed capabilities, keyed ``provider|model|base_url``.

    Loaded lazily on first access and never written unless :meth:`save` is called,
    so a read-only consumer (the pool) leaves the workspace untouched.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[str, CapabilityRecord] | None = None

    def _load(self) -> dict[str, CapabilityRecord]:
        if self._records is not None:
            return self._records
        records: dict[str, CapabilityRecord] = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring unreadable capability cache %s: %s", self.path, exc)
                raw = {}
            if isinstance(raw, dict):
                for key, value in raw.items():
                    try:
                        records[str(key)] = CapabilityRecord.model_validate(value)
                    except ValidationError as exc:
                        logger.warning("Skipping corrupt capability record %r: %s", key, exc)
        self._records = records
        return records

    def get(
        self, provider: str, model: str, base_url: str | None = None
    ) -> CapabilityRecord | None:
        return self._load().get(cache_key(provider, model, base_url))

    def put(self, record: CapabilityRecord) -> None:
        self._load()[cache_key(record.provider, record.model, record.base_url)] = record

    def records(self) -> list[CapabilityRecord]:
        return list(self._load().values())

    def save(self) -> None:
        from opentorus.atomicio import atomic_write_text

        payload = {
            key: record.model_dump(mode="json") for key, record in sorted(self._load().items())
        }
        atomic_write_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_capabilities(names: list[str]) -> tuple[frozenset[ProviderCapability], list[str]]:
    """Split declared capability names into known members and unknown strings."""
    known: set[ProviderCapability] = set()
    unknown: list[str] = []
    for name in names:
        try:
            known.add(ProviderCapability(str(name)))
        except ValueError:
            unknown.append(str(name))
    return frozenset(known), unknown


def effective_capabilities(
    profile: ModelProfile, cache: CapabilityCache | None = None
) -> frozenset[ProviderCapability]:
    """Static ∪ declared ∪ cached capabilities of a profile — never probes online.

    ``local_only`` is added when the profile runs locally (``is_local_provider`` or an
    explicit ``local_only: true``) and removed on an explicit ``local_only: false``,
    so a private-looking ``base_url`` that tunnels to a cloud API can be labelled
    honestly. Unknown declared names are ignored here; doctor reports them.
    """
    caps: set[ProviderCapability] = set(STATIC_CAPABILITIES.get(profile.provider.lower(), ()))
    declared, _unknown = parse_capabilities(profile.capabilities)
    caps |= declared
    if cache is not None:
        record = cache.get(profile.provider, profile.name, profile.base_url)
        if record is not None:
            cached, _ = parse_capabilities(record.capabilities)
            caps |= cached
    if profile_is_local(profile):
        caps.add(ProviderCapability.local_only)
    elif profile.local_only is False:
        caps.discard(ProviderCapability.local_only)
    return frozenset(caps)


def probe_and_cache(
    provider: BaseProvider, profile: ModelProfile, cache: CapabilityCache
) -> CapabilityRecord:
    """Probe tool calling online for ``profile`` and persist the result.

    Only ``opentorus doctor --capabilities --probe`` calls this: it costs a model
    call. The probe can confirm tool calling or stay inconclusive, never deny it (see
    ``tool_support.probe_tool_calling``); an inconclusive probe caches an empty record
    with the reason, so a later acquire still relies on declared capabilities.
    """
    from opentorus.providers.tool_support import probe_tool_calling

    ok, detail = probe_tool_calling(provider)
    caps: list[str] = []
    if ok is True:
        caps.append(ProviderCapability.tool_calling.value)
    if getattr(provider, "supports_streaming", False):
        caps.append(ProviderCapability.streaming.value)
    record = CapabilityRecord(
        provider=profile.provider,
        model=profile.name,
        base_url=profile.base_url,
        capabilities=caps,
        source="probe",
        probed_at=datetime.now(UTC),
        note=detail or None,
    )
    cache.put(record)
    cache.save()
    return record
