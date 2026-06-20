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
    raise ProviderError(
        f"Unknown provider '{config.model.provider}'. "
        "Valid providers: mock, openai, anthropic, ollama."
    )
