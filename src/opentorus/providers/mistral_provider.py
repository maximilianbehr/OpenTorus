"""Mistral (la Plateforme) through the OpenAI-compatible path.

Mistral serves ``/v1/chat/completions`` in OpenAI's request and response shape —
``tools``, ``tool_calls`` and ``usage`` included — so this reuses the OpenAI request
builder and message parser instead of adding a second SDK and a second tool-call
normalisation that would have to be kept in step by hand. What genuinely differs is
the credential (``MISTRAL_API_KEY``) and the default endpoint, and both are declared
here so ``provider: mistral`` works without a hand-written ``base_url``.

An explicit ``model.base_url`` still wins, which is what makes a proxy or a regional
endpoint configurable without a new provider.
"""

from __future__ import annotations

from opentorus.providers.openai_provider import OpenAIProvider

API_BASE = "https://api.mistral.ai/v1"


class MistralProvider(OpenAIProvider):
    name = "mistral"
    api_key_env = "MISTRAL_API_KEY"
    default_base_url = API_BASE


__all__ = ["API_BASE", "MistralProvider"]
