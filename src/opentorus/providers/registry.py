"""Resolve a provider from configuration.

Real providers are imported lazily so that missing optional SDKs never break
``import opentorus``. An unknown provider name raises a clear ProviderError.
"""

from __future__ import annotations

from opentorus.config import Config
from opentorus.errors import ProviderError
from opentorus.providers.base import BaseProvider
from opentorus.providers.mock_provider import MockProvider


def get_provider(config: Config) -> BaseProvider:
    name = config.model.provider.lower()
    if name == "mock":
        return MockProvider()
    if name == "openai":
        from opentorus.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(config)
    if name == "anthropic":
        from opentorus.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config)
    if name == "ollama":
        from opentorus.providers.ollama_provider import OllamaProvider

        return OllamaProvider(config)
    if name == "mistral":
        from opentorus.providers.mistral_provider import MistralProvider

        return MistralProvider(config)
    raise ProviderError(
        f"Unknown provider '{config.model.provider}'. "
        "Valid providers: mock, openai, anthropic, ollama, mistral."
    )


def get_provider_for_profile(config: Config, profile_name: str) -> BaseProvider:
    """Build the provider for one named profile from ``models.profiles``.

    A thin wrapper over :func:`get_provider` on a profile-derived config; the
    implicit ``default`` profile (the ``model:`` block) is always resolvable. Use
    :class:`opentorus.providers.pool.ProviderPool` when the choice should be
    routed and recorded.
    """
    from opentorus.providers.pool import ProviderPool, profile_config

    profiles = ProviderPool(config).profiles()
    profile = profiles.get(profile_name)
    if profile is None:
        raise ProviderError(
            f"Unknown model profile '{profile_name}'. Known profiles: "
            f"{', '.join(sorted(profiles)) or 'default'}."
        )
    return get_provider(profile_config(config, profile))
