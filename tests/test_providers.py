"""Tests for provider resolution and config mutation (Milestone 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.config import CONFIG_FILENAME, default_config, load_config, set_dotted
from opentorus.errors import ConfigError, ProviderError
from opentorus.providers.mock_provider import MockProvider
from opentorus.providers.registry import get_provider
from opentorus.repl import _handle_model, dispatch
from opentorus.workspace import init_workspace, workspace_dir


def test_get_provider_mock_by_default() -> None:
    assert isinstance(get_provider(default_config()), MockProvider)


def test_get_provider_unknown_raises() -> None:
    config = set_dotted(default_config(), "model.provider", "does-not-exist")
    with pytest.raises(ProviderError):
        get_provider(config)


def test_get_provider_real_lazy_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    # Construction now checks that the optional SDK is importable, so stub it:
    # the point of this test is the *key*, and it must hold whether or not the
    # real package is installed in the environment running the suite.
    stub = types.ModuleType("openai")
    stub.OpenAI = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", stub)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = set_dotted(default_config(), "model.provider", "openai")
    provider = get_provider(config)  # construction must not require a key
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        provider.generate([])


def test_set_dotted_coerces_types() -> None:
    config = set_dotted(default_config(), "model.temperature", "0.7")
    assert config.model.temperature == pytest.approx(0.7)
    config = set_dotted(config, "privacy.sensitive_file_guard", "false")
    assert config.privacy.sensitive_file_guard is False


def test_set_dotted_unknown_key_raises() -> None:
    with pytest.raises(ConfigError):
        set_dotted(default_config(), "model.nope", "x")


def test_set_dotted_max_steps_allows_inf() -> None:
    import math

    for token in ("inf", "infinity", "unlimited", "-1"):
        config = set_dotted(default_config(), "agent.max_steps", token)
        assert math.isinf(config.agent.max_steps)
    config = set_dotted(default_config(), "agent.max_steps", "1000")
    assert config.agent.max_steps == 1000


def test_repl_model_set_persists(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    out = _handle_model("set provider anthropic", tmp_path)
    assert "anthropic" in out
    config = load_config(workspace_dir(tmp_path) / CONFIG_FILENAME)
    assert config.model.provider == "anthropic"


def test_repl_context_and_model_show(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ctx = dispatch("/context", tmp_path)
    assert any("available tools" in m for m in ctx.messages)
    model = dispatch("/model", tmp_path)
    assert any("provider" in m for m in model.messages)


def test_get_provider_openai_reports_a_missing_sdk_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional SDK is checked when the provider is built, not one step in.

    Without it, a run initialised its workspace, fetched papers and built a
    container before dying inside the first agent step — the whole session's
    setup was the price of finding out.
    """
    import sys

    monkeypatch.setitem(sys.modules, "openai", None)
    config = set_dotted(default_config(), "model.provider", "openai")
    with pytest.raises(ProviderError, match="pip install openai"):
        get_provider(config)


# --- transient provider failures ------------------------------------------------------------


def _stub_sdk(monkeypatch, *, raises=None, captured=None):  # noqa: ANN001, ANN202
    """A fake ``openai`` module: records client kwargs, or fails the way the SDK does."""
    import sys
    import types

    class FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            if captured is not None:
                captured["request"] = kwargs
            if raises is not None:
                raise raises
            return types.SimpleNamespace(
                model="m",
                usage=None,
                choices=[
                    types.SimpleNamespace(
                        finish_reason="stop",
                        message=types.SimpleNamespace(content="ok", tool_calls=None),
                    )
                ],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):  # noqa: ANN003
            if captured is not None:
                captured["client"] = kwargs
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    stub = types.ModuleType("openai")
    stub.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-secret")


def test_max_retries_reaches_the_sdk_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK's own default is 2, which a long metered run outlives easily."""
    captured: dict = {}
    _stub_sdk(monkeypatch, captured=captured)
    config = set_dotted(default_config(), "model.provider", "openai")
    config = set_dotted(config, "model.max_retries", "7")
    get_provider(config).generate([])
    assert captured["client"]["max_retries"] == 7


def test_a_rate_limit_becomes_an_actionable_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 reached the user as a raw SDK traceback after the run had spent money."""

    class RateLimitError(Exception):
        status_code = 429

    _stub_sdk(monkeypatch, raises=RateLimitError("Error code: 429 - rate limit exceeded"))
    config = set_dotted(default_config(), "model.provider", "openai")
    with pytest.raises(ProviderError) as excinfo:
        get_provider(config).generate([])
    message = str(excinfo.value)
    assert "429" in message
    assert "max_retries" in message, "it must name the knob that fixes it"


def test_an_auth_failure_names_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    class AuthenticationError(Exception):
        status_code = 401

    _stub_sdk(monkeypatch, raises=AuthenticationError("Error code: 401 - Invalid API Key"))
    config = set_dotted(default_config(), "model.provider", "openai")
    with pytest.raises(ProviderError, match="401"):
        get_provider(config).generate([])


def test_an_unrecognised_sdk_failure_still_becomes_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing from the SDK may escape as its own type — the loop only handles ours."""
    _stub_sdk(monkeypatch, raises=ValueError("something the SDK did not document"))
    config = set_dotted(default_config(), "model.provider", "openai")
    with pytest.raises(ProviderError, match="ValueError"):
        get_provider(config).generate([])


def test_yaml_bare_off_is_accepted_for_literal_fields() -> None:
    """YAML 1.1 reads a bare ``off`` as False; a config written the way the shipped
    comment documents it must not take the whole workspace config down."""
    import yaml

    from opentorus.config import Config

    parsed = yaml.safe_load("dlp_pii: off\nembeddings_backend: off\n")
    assert parsed["dlp_pii"] is False, "this is the YAML behaviour being defended against"

    config = default_config()
    config = set_dotted(config, "governance.dlp_pii", "off")
    assert config.governance.dlp_pii == "off"

    # …and straight through model validation, which is the path a config file takes.
    revalidated = Config.model_validate(
        {
            **config.model_dump(mode="python"),
            "governance": {**config.governance.model_dump(mode="python"), "dlp_pii": False},
        }
    )
    assert revalidated.governance.dlp_pii == "off"


def test_an_unknown_literal_value_is_still_rejected() -> None:
    """Coercing False must not turn the field into a free-text one."""
    with pytest.raises(ConfigError):
        set_dotted(default_config(), "governance.dlp_pii", "sometimes")


def test_mistral_provider_targets_la_plateforme(monkeypatch: pytest.MonkeyPatch) -> None:
    """`provider: mistral` reaches Mistral with MISTRAL_API_KEY and no hand-set base_url."""
    from opentorus.providers.mistral_provider import API_BASE

    captured: dict = {}
    _stub_sdk(monkeypatch, captured=captured)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = set_dotted(default_config(), "model.provider", "mistral")
    config = set_dotted(config, "model.name", "zai-glm-5-2")
    response = get_provider(config).generate([])

    assert captured["client"]["base_url"] == API_BASE
    assert captured["client"]["api_key"] == "test-key-not-a-real-secret"
    assert captured["request"]["model"] == "zai-glm-5-2"
    assert response.content == "ok"


def test_mistral_base_url_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit base_url still wins — that is how a proxy or region is reached."""
    captured: dict = {}
    _stub_sdk(monkeypatch, captured=captured)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key-not-a-real-secret")

    config = set_dotted(default_config(), "model.provider", "mistral")
    config = set_dotted(config, "model.base_url", "https://proxy.internal/v1")
    get_provider(config).generate([])

    assert captured["client"]["base_url"] == "https://proxy.internal/v1"


def test_mistral_without_key_names_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error must name MISTRAL_API_KEY — not the inherited OPENAI_API_KEY."""
    import sys
    import types

    stub = types.ModuleType("openai")
    stub.OpenAI = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", stub)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    # A stray OpenAI key must not make the Mistral provider look configured.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")

    config = set_dotted(default_config(), "model.provider", "mistral")
    provider = get_provider(config)
    with pytest.raises(ProviderError, match="MISTRAL_API_KEY"):
        provider.generate([])


def test_mistral_api_key_is_scrubbed_from_provider_context() -> None:
    """The key must never ride along in context — it is in the credential list."""
    from opentorus.privacy import CREDENTIAL_ENV_NAMES

    assert "MISTRAL_API_KEY" in CREDENTIAL_ENV_NAMES
