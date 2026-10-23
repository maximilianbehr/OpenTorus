"""Reasoning effort: config, per-task-class routing, and the request payloads."""

from __future__ import annotations

import json

import pytest

from opentorus.agent.session import SessionMessage
from opentorus.config import Config, ModelProfile, default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.ollama_provider import build_ollama_chat_body
from opentorus.providers.openai_provider import build_openai_request, unsupported_request_field
from opentorus.providers.pool import ProviderPool

_MSGS = [SessionMessage(role="user", content="hi")]


def _openai_config(effort, *, base_url="http://localhost:8004/v1", api="auto") -> Config:
    config = default_config()
    config.model.provider = "openai"
    config.model.name = "qwen3.8-flash-next-nvfp4"
    config.model.base_url = base_url
    config.model.reasoning_effort = effort
    config.model.reasoning_api = api
    return config


def test_no_effort_sends_nothing_new() -> None:
    kwargs = build_openai_request(_openai_config(None), _MSGS, None)
    assert "extra_body" not in kwargs and "reasoning_effort" not in kwargs
    body = build_ollama_chat_body(default_config(), _MSGS, None)
    assert "think" not in body


def test_vllm_endpoint_gets_chat_template_kwargs_and_reasoning_effort() -> None:
    kwargs = build_openai_request(_openai_config("high"), _MSGS, None)
    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert kwargs["reasoning_effort"] == "high"


def test_off_disables_thinking_on_a_chat_template_server() -> None:
    kwargs = build_openai_request(_openai_config("off"), _MSGS, None)
    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "reasoning_effort" not in kwargs  # "minimal" is OpenAI-only


def test_openai_proper_gets_only_reasoning_effort_mapped_to_its_scale() -> None:
    kwargs = build_openai_request(_openai_config("max", base_url=None), _MSGS, None)
    assert kwargs["reasoning_effort"] == "high" and "extra_body" not in kwargs
    kwargs = build_openai_request(_openai_config("off", base_url=None), _MSGS, None)
    assert kwargs["reasoning_effort"] == "minimal"


@pytest.mark.parametrize(
    ("api", "has_extra", "has_effort"),
    [
        ("chat_template_kwargs", True, False),
        ("reasoning_effort", False, True),
        ("both", True, True),
        ("none", False, False),
    ],
)
def test_reasoning_api_selects_the_fields(api: str, has_extra: bool, has_effort: bool) -> None:
    kwargs = build_openai_request(_openai_config("medium", api=api), _MSGS, None)
    assert ("extra_body" in kwargs) is has_extra
    assert ("reasoning_effort" in kwargs) is has_effort


def test_rejected_reasoning_fields_are_droppable() -> None:
    exc = Exception(
        "Error code: 400 - Unsupported parameter: 'reasoning_effort' is not supported "
        "with this model."
    )
    assert unsupported_request_field(exc) == "reasoning_effort"
    forbidden = Exception(
        "422 {'type': 'extra_forbidden', 'loc': ['body', 'chat_template_kwargs'], 'input': {}}"
    )
    assert unsupported_request_field(forbidden) == "extra_body"


def test_ollama_think_field() -> None:
    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "qwen3:32b"
    config.model.reasoning_effort = "off"
    assert build_ollama_chat_body(config, _MSGS, None)["think"] is False
    config.model.reasoning_effort = "high"
    assert build_ollama_chat_body(config, _MSGS, None)["think"] is True
    config.model.name = "gpt-oss:120b"
    assert build_ollama_chat_body(config, _MSGS, None)["think"] == "high"
    config.model.reasoning_effort = "max"
    assert build_ollama_chat_body(config, _MSGS, None)["think"] == "high"
    config.model.reasoning_effort = "off"
    assert build_ollama_chat_body(config, _MSGS, None)["think"] == "low"
    json.dumps(build_ollama_chat_body(config, _MSGS, None))  # serialisable


class _Recorder(BaseProvider):
    name = "rec"

    def __init__(self, config: Config) -> None:
        self.config = config

    def generate(self, messages, tools=None):  # type: ignore[override]
        return ProviderResponse(kind="message", content="ok")


def test_pool_applies_task_effort_per_class(tmp_path) -> None:  # noqa: ANN001
    config = default_config()
    config.models.profiles["fast"] = ModelProfile(
        provider="openai", name="m", base_url="http://x/v1", reasoning_effort="low"
    )
    config.models.default_profile = "fast"
    config.governance.routing.task_effort = {"proof_development": "high", "narration": "off"}
    pool = ProviderPool(config, ot_dir=None, factory=_Recorder)
    proof = pool.acquire("proof_development")
    narr = pool.acquire("narration")
    other = pool.acquire("code_generation")
    assert proof.provider.config.model.reasoning_effort == "high"
    assert narr.provider.config.model.reasoning_effort == "off"
    assert other.provider.config.model.reasoning_effort == "low"  # the profile's own
    assert proof.decision.reasoning_effort == "high"
    assert proof.provider is not narr.provider  # one instance per (profile, effort)
    # The legacy alias and the default entry are honoured.
    config.governance.routing.task_effort = {"proof": "max", "default": "medium"}
    pool = ProviderPool(config, ot_dir=None, factory=_Recorder)
    assert pool.acquire("proof_development").provider.config.model.reasoning_effort == "max"
    assert pool.acquire("narration").provider.config.model.reasoning_effort == "medium"
