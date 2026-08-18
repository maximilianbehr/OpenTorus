"""Tests for provider capabilities: static table, declared, cached probes — no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentorus.config import ModelProfile, default_config
from opentorus.providers.capabilities import (
    STATIC_CAPABILITIES,
    CapabilityCache,
    CapabilityRecord,
    ProviderCapability,
    cache_key,
    default_cache_path,
    effective_capabilities,
    is_local_provider,
    probe_and_cache,
)


def test_static_table_per_provider_kind() -> None:
    C = ProviderCapability
    assert STATIC_CAPABILITIES["mock"] == {
        C.tool_calling,
        C.streaming,
        C.structured_output,
        C.local_only,
    }
    assert STATIC_CAPABILITIES["openai"] == {
        C.tool_calling,
        C.structured_output,
        C.json_schema,
        C.vision,
        C.large_context,
    }
    assert STATIC_CAPABILITIES["anthropic"] == {
        C.tool_calling,
        C.structured_output,
        C.vision,
        C.large_context,
    }
    # Ollama tool calling depends on the pulled model: never static.
    assert STATIC_CAPABILITIES["ollama"] == {C.streaming, C.local_only}
    assert C.tool_calling not in STATIC_CAPABILITIES["ollama"]
    assert {c.value for c in C} == {
        "tool_calling",
        "streaming",
        "structured_output",
        "vision",
        "large_context",
        "local_only",
        "formalization_support",
        "json_schema",
    }


def test_effective_capabilities_is_static_union_declared_union_cached(tmp_path: Path) -> None:
    profile = ModelProfile(provider="ollama", name="qwen", capabilities=["tool_calling", "bogus"])
    caps = effective_capabilities(profile, None)
    assert ProviderCapability.tool_calling in caps  # declared
    assert ProviderCapability.streaming in caps  # static
    assert ProviderCapability.local_only in caps  # ollama is local
    assert ProviderCapability.vision not in caps

    cache = CapabilityCache(tmp_path / "caps.json")
    cache.put(
        CapabilityRecord(provider="ollama", model="qwen", capabilities=["vision"], source="probe")
    )
    assert ProviderCapability.vision in effective_capabilities(profile, cache)
    # A different model's cache entry does not leak.
    other = ModelProfile(provider="ollama", name="llama")
    assert ProviderCapability.vision not in effective_capabilities(other, cache)


def test_local_only_override_and_detection() -> None:
    cloud = ModelProfile(provider="openai", name="gpt")
    assert ProviderCapability.local_only not in effective_capabilities(cloud)
    private = ModelProfile(provider="openai", name="gpt", base_url="http://192.168.1.5:8000/v1")
    assert ProviderCapability.local_only in effective_capabilities(private)
    tunnelled = ModelProfile(
        provider="openai", name="gpt", base_url="http://localhost:9/v1", local_only=False
    )
    assert ProviderCapability.local_only not in effective_capabilities(tunnelled)
    forced = ModelProfile(provider="openai", name="gpt", local_only=True)
    assert ProviderCapability.local_only in effective_capabilities(forced)
    assert is_local_provider("ollama") is True
    assert is_local_provider("openai", "https://api.openai.com/v1") is False


def test_cache_round_trip_is_atomic_json(tmp_path: Path) -> None:
    path = tmp_path / "providers" / "capabilities.json"
    cache = CapabilityCache(path)
    assert cache.get("openai", "gpt-x") is None
    when = datetime(2026, 1, 1, tzinfo=UTC)
    cache.put(
        CapabilityRecord(
            provider="openai",
            model="gpt-x",
            base_url=None,
            capabilities=["tool_calling"],
            source="probe",
            probed_at=when,
        )
    )
    cache.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert list(raw) == [cache_key("openai", "gpt-x", None)] == ["openai|gpt-x|"]
    assert raw["openai|gpt-x|"]["capabilities"] == ["tool_calling"]
    # No temp file left behind by the atomic write.
    assert [p.name for p in path.parent.iterdir()] == ["capabilities.json"]
    reloaded = CapabilityCache(path).get("openai", "gpt-x")
    assert reloaded is not None
    assert reloaded.probed_at == when
    assert reloaded.source == "probe"


def test_cache_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "capabilities.json"
    path.write_text("{not json", encoding="utf-8")
    cache = CapabilityCache(path)
    assert cache.get("openai", "x") is None
    path.write_text(json.dumps({"k": {"provider": 1}}), encoding="utf-8")
    assert CapabilityCache(path).records() == []


def test_default_cache_path_lives_under_providers(tmp_path: Path) -> None:
    assert default_cache_path(tmp_path) == tmp_path / "providers" / "capabilities.json"


def test_acquire_never_probes_online(monkeypatch, tmp_path: Path) -> None:
    import opentorus.providers.tool_support as tool_support
    from opentorus.providers.pool import ProviderPool, TaskClass

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("acquire must not probe")

    monkeypatch.setattr(tool_support, "probe_tool_calling", _boom)
    monkeypatch.setattr(tool_support, "provider_supports_tool_calling", _boom)
    config = default_config()
    config.models.profiles = {"o": ModelProfile(provider="ollama", name="qwen")}
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["o"]}
    pool = ProviderPool(config, ot_dir=tmp_path / ".opentorus")
    lease = pool.acquire(TaskClass.narration)
    assert lease.profile_name == "o"
    # Requiring tool calling on an undeclared Ollama profile falls back — still no probe.
    lease = pool.acquire(
        TaskClass.narration, required_capabilities=frozenset({ProviderCapability.tool_calling})
    )
    assert lease.profile_name == "default"
    assert lease.decision.fallback_reason is not None
    assert "tool_calling" in lease.decision.fallback_reason


def test_probe_and_cache_records_confirmed_tool_calling(monkeypatch, tmp_path: Path) -> None:
    import opentorus.providers.tool_support as tool_support
    from opentorus.providers.mock_provider import MockProvider

    monkeypatch.setattr(tool_support, "probe_tool_calling", lambda provider, **kw: (True, ""))
    cache = CapabilityCache(tmp_path / "caps.json")
    profile = ModelProfile(provider="ollama", name="qwen")
    record = probe_and_cache(MockProvider(), profile, cache)
    assert "tool_calling" in record.capabilities
    assert record.source == "probe"
    assert record.probed_at is not None
    assert cache.path.is_file()
    assert ProviderCapability.tool_calling in effective_capabilities(
        profile, CapabilityCache(cache.path)
    )

    monkeypatch.setattr(
        tool_support, "probe_tool_calling", lambda provider, **kw: (None, "text reply")
    )
    record = probe_and_cache(MockProvider(), ModelProfile(provider="ollama", name="x"), cache)
    assert "tool_calling" not in record.capabilities
    assert record.note == "text reply"


@pytest.mark.parametrize("name", ["tool_calling", "vision", "local_only"])
def test_capability_enum_is_string_valued(name: str) -> None:
    assert ProviderCapability(name) == name
    assert str(ProviderCapability(name)) == name
