"""Detect whether the configured model provider can read image inputs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentorus.config import Config
    from opentorus.providers.base import BaseProvider

# Substrings that usually indicate a multimodal checkpoint (fallback when API omits caps).
_VISION_NAME_HINTS = (
    "llava",
    "moondream",
    "bakllava",
    "minicpm-v",
    "gemma3",
    "llama3.2-vision",
    "llama3.2:vision",
    "qwen2-vl",
    "qwen-vl",
    "qwen3-vl",
    "mistral-small",
    "pixtral",
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4.1",
    "gpt-5",
    "o1",
    "o3",
    "o4",
    "claude-3",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-haiku-4",
    "vision",
)


def _name_suggests_vision(model_name: str) -> bool:
    low = model_name.lower()
    return any(hint in low for hint in _VISION_NAME_HINTS)


def _ollama_reports_vision(host: str, model_name: str) -> tuple[bool, str]:
    """Query ``/api/show`` for Ollama vision capability."""
    url = f"{host.rstrip('/')}/api/show"
    body = json.dumps({"name": model_name}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return False, f"Could not query Ollama at {host}: {exc}"
    except json.JSONDecodeError:
        return False, f"Ollama returned invalid JSON from /api/show for '{model_name}'."

    capabilities = data.get("capabilities") or []
    if isinstance(capabilities, list) and "vision" in capabilities:
        return True, ""

    modelfile = str(data.get("modelfile", "")).lower()
    if "clip" in modelfile or "projector" in modelfile:
        return True, ""

    if _name_suggests_vision(model_name):
        return True, ""

    caps_text = ", ".join(capabilities) if capabilities else "none reported"
    return (
        False,
        f"Ollama model '{model_name}' has no vision component (capabilities: {caps_text}). "
        "Pull a vision model, e.g. `ollama pull llava` or `ollama pull llama3.2-vision`, "
        "then `opentorus config set model.name llava`.",
    )


def provider_supports_vision(
    provider: BaseProvider | None,
    config: Config | None = None,
) -> tuple[bool, str]:
    """Return ``(True, "")`` when the provider can consume PNG page images."""
    if provider is None:
        return False, "No model provider is configured."

    if getattr(provider, "supports_vision", False):
        return True, ""

    name = getattr(provider, "name", "mock")
    if name == "mock":
        return (
            False,
            "The mock provider cannot read images. Configure ollama/openai/anthropic "
            "with a vision-capable model.",
        )

    cfg = config or getattr(provider, "config", None)
    model_name = getattr(getattr(cfg, "model", None), "name", "") if cfg else ""

    if name == "ollama":
        if not model_name:
            return False, "No Ollama model name configured (`opentorus config set model.name …`)."
        host = getattr(getattr(cfg, "model", None), "base_url", None) or "http://localhost:11434"
        return _ollama_reports_vision(host, model_name)

    if not model_name:
        return False, f"No model name configured for provider '{name}'."

    if _name_suggests_vision(model_name):
        return True, ""

    if name == "openai":
        return (
            False,
            f"OpenAI model '{model_name}' does not look vision-capable. "
            "Use e.g. gpt-4o or gpt-4-turbo for `--vision`.",
        )
    if name == "anthropic":
        return (
            False,
            f"Anthropic model '{model_name}' does not look vision-capable. "
            "Use Claude 3+ / Sonnet / Opus for `--vision`.",
        )

    return (
        False,
        f"Provider '{name}' (model '{model_name}') does not advertise vision support.",
    )


def require_vision_provider(
    provider: BaseProvider | None,
    config: Config | None = None,
    *,
    context: str = "--vision",
) -> None:
    """Raise :class:`OpenTorusError` when images cannot be sent to the model."""
    from opentorus.errors import OpenTorusError

    ok, detail = provider_supports_vision(provider, config)
    if ok:
        return
    raise OpenTorusError(
        f"{context} requires a vision-capable model, but the current setup cannot read "
        f"page images. {detail}"
    )
