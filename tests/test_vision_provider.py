"""Tests for vision capability detection."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.providers.vision import provider_supports_vision, require_vision_provider

runner = CliRunner()


def test_mock_provider_not_vision() -> None:
    class MockProvider:
        name = "mock"

    ok, detail = provider_supports_vision(MockProvider())  # type: ignore[arg-type]
    assert ok is False
    assert "mock" in detail.lower()


def test_ollama_vision_from_capabilities() -> None:
    class OllamaProvider:
        name = "ollama"
        config = Config()
        config.model.name = "llava"
        config.model.base_url = "http://localhost:11434"

    payload = json.dumps({"capabilities": ["vision", "completion"]}).encode()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return payload

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        ok, detail = provider_supports_vision(OllamaProvider())  # type: ignore[arg-type]
    assert ok is True
    assert detail == ""


def test_ollama_text_only_model_rejected() -> None:
    class OllamaProvider:
        name = "ollama"
        config = Config()
        config.model.name = "qwen3:8b"
        config.model.base_url = "http://localhost:11434"

    payload = json.dumps({"capabilities": ["completion"]}).encode()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return payload

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        ok, detail = provider_supports_vision(OllamaProvider())  # type: ignore[arg-type]
    assert ok is False
    assert "no vision component" in detail.lower()


def test_require_vision_raises() -> None:
    class MockProvider:
        name = "mock"

    with pytest.raises(OpenTorusError, match="vision-capable"):
        require_vision_provider(MockProvider())  # type: ignore[arg-type]
