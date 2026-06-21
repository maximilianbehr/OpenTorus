"""Detect whether the configured model can call tools.

OpenTorus is an agent: every deliverable (proof_write, exp_run, claim_new, …) is a
tool call. A model that cannot call tools produces only chat and makes no progress, so
it must be refused with a clear message rather than burning a long run that ends empty.

Detection order, cheapest first:
- ``mock`` always supports tools (deterministic test provider).
- ``ollama`` reports a ``tools`` capability via ``/api/show`` (authoritative when present).
- otherwise (openai / anthropic / any OpenAI-compatible local endpoint, where the model
  name is not a reliable signal) a one-shot *probe*: send a trivial tool and check the
  model actually returns a tool call.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentorus.config import Config
    from opentorus.providers.base import BaseProvider

_PROBE_TOOL = {
    "name": "ot_capability_ping",
    "description": "Capability probe — call this tool with ok=true and nothing else.",
    "parameters": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    },
}
_PROBE_PROMPT = "Call the ot_capability_ping tool with ok=true. Reply only with the tool call."


def _model_name(provider: BaseProvider, config: Config | None) -> str:
    cfg = config or getattr(provider, "config", None)
    return getattr(getattr(cfg, "model", None), "name", "") or ""


def _ollama_reports_tools(host: str, model_name: str) -> tuple[bool | None, str]:
    """Query ``/api/show`` for an Ollama ``tools`` capability.

    Returns ``(True, "")`` if advertised, ``(False, reason)`` if the server reports
    capabilities but not ``tools``, or ``(None, "")`` when it cannot be determined (old
    Ollama / unreachable) so the caller falls back to a probe.
    """
    url = f"{host.rstrip('/')}/api/show"
    body = json.dumps({"name": model_name}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None, ""

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return None, ""  # server does not report capabilities → inconclusive
    if "tools" in capabilities:
        return True, ""
    caps_text = ", ".join(str(c) for c in capabilities)
    return (
        False,
        f"Ollama model '{model_name}' does not advertise tool calling "
        f"(capabilities: {caps_text}). Pull a tool-capable model "
        "(e.g. `ollama pull qwen3` or `ollama pull llama3.1`) and "
        "`opentorus config set model.name …`.",
    )


def probe_tool_calling(provider: BaseProvider, *, attempts: int = 2) -> tuple[bool | None, str]:
    """Send a trivial tool and check whether the model returns a tool call.

    The probe can only *confirm* tool support, never *deny* it: returns ``(True, "")``
    when a tool call comes back, otherwise ``(None, reason)``. A text reply is NOT
    treated as a definitive negative, because ``tool_choice="required"`` is not enforced
    by every provider (the base ``respond`` ignores it, and a non-compliant local
    OpenAI-compatible server may ignore it too) — so a single unforced text sample does
    not prove the model cannot call tools, and refusing a tool-capable model on that
    basis would be worse than proceeding. A definitive negative comes only from an
    authoritative source (Ollama ``/api/show``) or at runtime (zero tool calls executed).
    """
    from opentorus.agent.session import SessionMessage

    messages = [SessionMessage(role="user", content=_PROBE_PROMPT)]
    saw_text = False
    last_error = ""
    for _ in range(max(1, attempts)):
        try:
            try:
                response = provider.respond(messages, tools=[_PROBE_TOOL], tool_choice="required")
            except Exception:
                # Some providers reject tool_choice="required"; retry without forcing.
                response = provider.generate(messages, tools=[_PROBE_TOOL])
        except Exception as exc:  # noqa: BLE001 — any failure here is inconclusive, not fatal
            last_error = str(exc)
            continue
        if getattr(response, "kind", None) == "tool_call" or bool(
            getattr(response, "tool_calls", None)
        ):
            return True, ""
        saw_text = True

    if saw_text:
        return None, (
            "the model replied with text rather than a tool call on a capability probe; "
            "it may not support tool calling"
        )
    return None, f"could not verify tool calling (the probe request failed: {last_error})"


def provider_supports_tool_calling(
    provider: BaseProvider | None,
    config: Config | None = None,
    *,
    allow_probe: bool = True,
) -> tuple[bool | None, str]:
    """Return whether the provider's model can call tools.

    ``True`` supported, ``False`` definitively not, ``None`` could not be determined.
    """
    if provider is None:
        return False, "No model provider is configured."
    name = getattr(provider, "name", "mock")
    if name == "mock":
        return True, ""

    if name == "ollama":
        cfg = config or getattr(provider, "config", None)
        host = getattr(getattr(cfg, "model", None), "base_url", None) or "http://localhost:11434"
        verdict, detail = _ollama_reports_tools(host, _model_name(provider, config))
        if verdict is not None:
            return verdict, detail
        # inconclusive (old Ollama) → fall through to the probe

    if allow_probe:
        return probe_tool_calling(provider)
    return None, ""


def require_tool_calling_provider(
    provider: BaseProvider | None,
    config: Config | None = None,
    *,
    warn: object = None,
) -> None:
    """Refuse to run when the model definitively cannot call tools.

    ``warn`` is an optional ``Callable[[str], None]`` used to surface a non-fatal notice
    when capability could not be verified (so a transient probe failure never blocks a
    run). A definitive negative raises :class:`OpenTorusError`.
    """
    cfg = config or getattr(provider, "config", None)
    if cfg is not None and not getattr(getattr(cfg, "model", None), "verify_tool_calling", True):
        return

    ok, detail = provider_supports_tool_calling(provider, config)
    if ok is True:
        return

    model_name = _model_name(provider, config) if provider is not None else ""
    if ok is None:
        # Inconclusive — warn but do not block (the probe may have failed transiently).
        if callable(warn):
            warn(
                f"Could not confirm that model '{model_name}' supports tool calling: "
                f"{detail}. Proceeding; if the run ends with no tool calls, switch to a "
                "tool-calling model or set model.verify_tool_calling false to silence this."
            )
        return

    from opentorus.errors import ProviderError

    raise ProviderError(
        f"Model '{model_name}' does not support tool calling: {detail}. "
        "OpenTorus drives every deliverable through tool calls, so this model cannot be "
        "used for agent runs. Configure a tool-calling model (e.g. a recent OpenAI/Claude "
        "chat model, or `ollama pull qwen3`), or set model.verify_tool_calling false to "
        "skip this check."
    )
