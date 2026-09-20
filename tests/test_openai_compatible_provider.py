"""The generic OpenAI-compatible engine adapter + its provider registry.

Covers the three things the adapter promises (no network anywhere):

  1. Chat Completions wire shape — `client.chat.completions.create` with
     `messages` / `max_tokens`, NOT the Responses API `providers/openai.py`
     uses, against the registry's `base_url`.
  2. Per-provider reasoning dials — `thinking_budget` is forwarded only as
     the field each provider documents (DeepSeek/Z.ai `thinking` object,
     Groq/Mistral/Ollama `reasoning_effort`, nothing for xAI/aggregators/custom).
  3. Config resolution — every registry provider resolves its key env; ollama
     needs no key but needs a model; custom needs ROADMODEL_BASE_URL /
     ROADMODEL_API_KEY / ROADMODEL_MODEL; the missing-variable error names
     the right variable.

The fake OpenAI client is contract-validated against the REAL SDK's
`chat.completions.create` signature (memory: monkeypatched mocks need
contract validation) so a renamed SDK kwarg fails here, not in prod.
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from roadmodel.config import (
    PROVIDER_CHOICES,
    PROVIDER_KEY_ENV,
    PROVIDER_ORDER,
    load_config,
)
from roadmodel.errors import MissingProviderKeyError, ProviderCallError
from roadmodel.providers import ProviderAdapter
from roadmodel.providers import openai as openai_provider
from roadmodel.providers.openai_compatible import (
    ADAPTERS,
    OpenAICompatibleAdapter,
    _extract_message_text,
)
from roadmodel.providers.registry import (
    COMPATIBLE_PROVIDERS,
    OLLAMA_PLACEHOLDER_KEY,
    resolve_base_url,
)
from roadmodel.recommend import PROVIDER_ADAPTERS

_RESPONSE = (
    "MODEL: x\nPLATFORM: y\nEFFORT: Low\nTHINKING: Off\nCONVERSATION: New\nRATIONALE: stub\n"
)

_ALL_ENV = [
    *PROVIDER_KEY_ENV.values(),
    "ROADMODEL_PROVIDER",
    "ROADMODEL_MODEL",
    "ROADMODEL_BASE_URL",
    "ROADMODEL_USER_CONTEXT",
    "OLLAMA_HOST",
]


# ------------------------------------------------------------------ fake SDK


class _FakeCompletions:
    def create(self, **kwargs: Any) -> Any:
        _FakeClient.captured = dict(kwargs)
        return _FakeClient.response


class _FakeClient:
    captured: dict[str, Any] = {}
    init_kwargs: dict[str, Any] = {}
    response: Any = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeClient.init_kwargs = dict(kwargs)
        self.chat = types.SimpleNamespace(completions=_FakeCompletions())


def _message_response(content: Any, **extra: Any) -> Any:
    message = types.SimpleNamespace(content=content, role="assistant", **extra)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _install_fake(monkeypatch: pytest.MonkeyPatch, response: Any = None) -> None:
    _FakeClient.captured = {}
    _FakeClient.init_kwargs = {}
    _FakeClient.response = response if response is not None else _message_response(_RESPONSE)
    fake_openai = types.ModuleType("openai")

    class _FakeAPIError(Exception):
        pass

    fake_openai.OpenAI = _FakeClient  # type: ignore[attr-defined]
    fake_openai.APIError = _FakeAPIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)


def test_fake_matches_real_sdk_contract() -> None:
    """Every kwarg the adapter sends must be a real parameter of the SDK's
    `chat.completions.create` (and `OpenAI(...)` must take base_url) —
    otherwise the fake would pass while prod 400s."""
    real = pytest.importorskip("openai")
    create_params = inspect.signature(real.resources.chat.Completions.create).parameters
    for name in (
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "reasoning_effort",
        "extra_body",
    ):
        assert name in create_params, name
    init_params = inspect.signature(real.OpenAI.__init__).parameters
    for name in ("base_url", "timeout", "max_retries"):
        assert name in init_params, name


# --------------------------------------------------------------- wire shape


def test_uses_chat_completions_against_registry_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)
    text = ADAPTERS["deepseek"].recommend("P", "S", api_key="k", max_output_tokens=512)
    assert text == _RESPONSE.strip()
    assert _FakeClient.init_kwargs == {"api_key": "k", "base_url": "https://api.deepseek.com"}
    sent = _FakeClient.captured
    assert sent["model"] == "deepseek-v4-pro"  # registry default
    assert sent["messages"] == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "P"},
    ]
    assert sent["max_tokens"] == 512  # Chat Completions name, not max_output_tokens
    assert "input" not in sent and "max_output_tokens" not in sent  # Responses-API keys
    assert "temperature" not in sent and "reasoning_effort" not in sent


def test_local_endpoints_get_long_timeout_and_no_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 32B model on local hardware takes minutes per call; the SDK's 10-minute
    default timeout plus 2 automatic retries turned one slow call into a
    30-minute silent redo (observed with Qwen3 via Ollama). Hosted providers
    keep the SDK defaults."""
    _install_fake(monkeypatch)
    ADAPTERS["ollama"].recommend("P", "S", api_key="k", model="m")
    assert _FakeClient.init_kwargs["timeout"] == 1800.0
    assert _FakeClient.init_kwargs["max_retries"] == 0
    monkeypatch.setenv("ROADMODEL_BASE_URL", "http://localhost:8000/v1")
    ADAPTERS["custom"].recommend("P", "S", api_key="k", model="m")
    assert _FakeClient.init_kwargs["timeout"] == 1800.0
    ADAPTERS["deepseek"].recommend("P", "S", api_key="k")
    assert "timeout" not in _FakeClient.init_kwargs
    assert "max_retries" not in _FakeClient.init_kwargs


def test_explicit_model_and_temperature_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)
    ADAPTERS["groq"].recommend("P", "S", api_key="k", model="openai/gpt-oss-20b", temperature=0.0)
    assert _FakeClient.captured["model"] == "openai/gpt-oss-20b"
    assert _FakeClient.captured["temperature"] == 0.0  # 0.0 is meaningful (greedy)


@pytest.mark.parametrize(
    ("provider", "budget", "expected"),
    [
        # DeepSeek / Z.ai: documented `thinking` toggle (+ reasoning_effort when on).
        ("deepseek", 0, {"extra_body": {"thinking": {"type": "disabled"}}}),
        (
            "deepseek",
            256,
            {"extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": "low"},
        ),
        ("zai", 0, {"extra_body": {"thinking": {"type": "disabled"}}}),
        # Groq gpt-oss: reasoning_effort low/medium/high, no off rung.
        ("groq", 0, {"reasoning_effort": "low"}),
        ("groq", 256, {"reasoning_effort": "low"}),
        # Mistral / Ollama document an explicit `none` rung.
        ("mistral", 0, {"reasoning_effort": "none"}),
        ("ollama", 0, {"reasoning_effort": "none"}),
        ("ollama", 256, {"reasoning_effort": "low"}),
        # No documented Chat-Completions dial: nothing is sent.
        ("xai", 0, {}),
        ("openrouter", 0, {}),
        ("together", 256, {}),
        ("custom", 0, {}),
    ],
)
def test_thinking_budget_maps_to_documented_dial(
    provider: str, budget: int, expected: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake(monkeypatch)
    monkeypatch.setenv("ROADMODEL_BASE_URL", "http://localhost:8000/v1")
    ADAPTERS[provider].recommend("P", "S", api_key="k", model="m", thinking_budget=budget)
    sent = _FakeClient.captured
    dials = {k: v for k, v in sent.items() if k in ("extra_body", "reasoning_effort")}
    assert dials == expected
    assert "thinking_budget" not in sent and "reasoning" not in sent


@pytest.mark.parametrize("provider", sorted(COMPATIBLE_PROVIDERS))
def test_no_dial_when_thinking_budget_unset(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)
    monkeypatch.setenv("ROADMODEL_BASE_URL", "http://localhost:8000/v1")
    ADAPTERS[provider].recommend("P", "S", api_key="k", model="m")
    assert "reasoning_effort" not in _FakeClient.captured
    assert "extra_body" not in _FakeClient.captured


# ------------------------------------------------------------ text extraction


def test_strips_inline_think_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, _message_response("<think>\nplan...\n</think>\n" + _RESPONSE))
    assert ADAPTERS["ollama"].recommend("P", "S", api_key="k", model="m") == _RESPONSE.strip()


def test_multipart_content_joined() -> None:
    response = _message_response([{"type": "text", "text": "MODEL: a\n"}, {"text": "PLATFORM: b"}])
    assert _extract_message_text(response) == "MODEL: a\nPLATFORM: b"


def test_reasoning_only_response_is_a_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A thinking model that spends the whole max_tokens budget reasoning
    returns content='' plus a `reasoning` field — the error must say so and
    point at the two knobs, not just 'no text'."""
    _install_fake(monkeypatch, _message_response("", reasoning="I need to classify..."))
    with pytest.raises(ProviderCallError) as excinfo:
        ADAPTERS["ollama"].recommend("P", "S", api_key="k", model="m")
    assert "reasoning but no visible text" in str(excinfo.value)
    assert "--max-output-tokens" in str(excinfo.value)


def test_empty_response_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, _message_response(None))
    with pytest.raises(ProviderCallError, match="Ollama response did not contain text"):
        ADAPTERS["ollama"].recommend("P", "S", api_key="k", model="m")


def test_api_error_is_wrapped_with_provider_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)

    def boom(self: Any, **kwargs: Any) -> Any:
        raise sys.modules["openai"].APIError("401 bad key")  # type: ignore[attr-defined]

    monkeypatch.setattr(_FakeCompletions, "create", boom)
    with pytest.raises(ProviderCallError, match="Groq API call failed: 401 bad key"):
        ADAPTERS["groq"].recommend("P", "S", api_key="k")


def test_missing_model_and_base_url_are_named_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)
    with pytest.raises(ProviderCallError, match="ROADMODEL_MODEL"):
        ADAPTERS["ollama"].recommend("P", "S", api_key="k")
    monkeypatch.delenv("ROADMODEL_BASE_URL", raising=False)
    with pytest.raises(ProviderCallError, match="ROADMODEL_BASE_URL"):
        ADAPTERS["custom"].recommend("P", "S", api_key="k", model="m")


def test_missing_sdk_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors tests/test_optional_providers.py for the new adapter."""
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderCallError) as excinfo:
        ADAPTERS["deepseek"].recommend("P", "S", api_key="k")
    assert "roadmodel[recommend]" in str(excinfo.value)


# ------------------------------------------------------------------- registry


def test_every_registry_provider_is_dispatchable_and_protocol_shaped() -> None:
    real_sig = inspect.signature(openai_provider.recommend)
    for name in COMPATIBLE_PROVIDERS:
        adapter = PROVIDER_ADAPTERS[name]
        assert isinstance(adapter, OpenAICompatibleAdapter)
        # Same keyword surface as the native adapters (ProviderAdapter Protocol).
        sig = inspect.signature(adapter.recommend)
        assert list(sig.parameters) == list(real_sig.parameters)
        for pname, param in sig.parameters.items():
            assert param.kind == real_sig.parameters[pname].kind, pname
    protocol_adapter: ProviderAdapter = ADAPTERS["custom"]  # static Protocol check
    assert protocol_adapter is ADAPTERS["custom"]
    assert PROVIDER_ADAPTERS["openai"] is openai_provider  # native adapters untouched


def test_registry_and_config_tables_agree() -> None:
    for name, spec in COMPATIBLE_PROVIDERS.items():
        assert PROVIDER_KEY_ENV[name] == spec.key_env  # type: ignore[index]
        assert name in PROVIDER_CHOICES
    assert set(PROVIDER_CHOICES) == set(PROVIDER_KEY_ENV)
    # Explicit-only providers never auto-detect from the environment.
    assert "ollama" not in PROVIDER_ORDER and "custom" not in PROVIDER_ORDER
    assert PROVIDER_ORDER[:3] == ("anthropic", "openai", "google")


def test_ollama_host_env_shapes_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = COMPATIBLE_PROVIDERS["ollama"]
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert resolve_base_url(spec) == "http://localhost:11434/v1"
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11435")
    assert resolve_base_url(spec) == "http://0.0.0.0:11435/v1"
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example/")
    assert resolve_base_url(spec) == "https://ollama.example/v1"


# --------------------------------------------------------- config resolution


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "roadmodel.config.user_context.resolve", lambda *, cli_path: tmp_path / "uc.md"
    )


@pytest.mark.parametrize(
    "provider", [n for n, s in COMPATIBLE_PROVIDERS.items() if s.key_required and n != "custom"]
)
def test_hosted_provider_resolves_its_key_env(
    provider: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    env_name = COMPATIBLE_PROVIDERS[provider].key_env
    monkeypatch.setenv(env_name, f"{provider}-secret")
    # explicit
    cfg = load_config(cli_provider=provider, cli_model="m", cli_user_context=None)
    assert (cfg.provider, cfg.api_key, cfg.model) == (provider, f"{provider}-secret", "m")
    # auto-detected: the only key present wins
    cfg = load_config(cli_provider=None, cli_model="m", cli_user_context=None)
    assert cfg.provider == provider


@pytest.mark.parametrize(
    "provider", [n for n, s in COMPATIBLE_PROVIDERS.items() if s.key_required and n != "custom"]
)
def test_hosted_provider_missing_key_names_variable(
    provider: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    env_name = COMPATIBLE_PROVIDERS[provider].key_env
    with pytest.raises(MissingProviderKeyError) as excinfo:
        load_config(cli_provider=provider, cli_model="m", cli_user_context=None)
    assert f"{env_name} is not set" in str(excinfo.value)


def test_provider_without_default_model_requires_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(MissingProviderKeyError, match="ROADMODEL_MODEL"):
        load_config(cli_provider="openrouter", cli_model=None, cli_user_context=None)
    monkeypatch.setenv("ROADMODEL_MODEL", "vendor/model")
    cfg = load_config(cli_provider="openrouter", cli_model=None, cli_user_context=None)
    assert cfg.model == "vendor/model"
    # --model beats ROADMODEL_MODEL, for every provider.
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cfg = load_config(cli_provider="openai", cli_model="gpt-x", cli_user_context=None)
    assert cfg.model == "gpt-x"
    cfg = load_config(cli_provider="openai", cli_model=None, cli_user_context=None)
    assert cfg.model == "vendor/model"


def test_ollama_needs_no_key_but_needs_a_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ROADMODEL_PROVIDER", "ollama")
    with pytest.raises(MissingProviderKeyError, match="ROADMODEL_MODEL"):
        load_config(cli_provider=None, cli_model=None, cli_user_context=None)
    monkeypatch.setenv("ROADMODEL_MODEL", "gemma3:12b")
    cfg = load_config(cli_provider=None, cli_model=None, cli_user_context=None)
    assert (cfg.provider, cfg.model, cfg.api_key) == (
        "ollama",
        "gemma3:12b",
        OLLAMA_PLACEHOLDER_KEY,
    )
    monkeypatch.setenv("OLLAMA_API_KEY", "remote-token")  # e.g. a proxied remote Ollama
    assert load_config(cli_provider=None, cli_model=None, cli_user_context=None).api_key == (
        "remote-token"
    )


def test_ollama_is_never_auto_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ROADMODEL_MODEL", "gemma3:12b")
    with pytest.raises(MissingProviderKeyError, match="No provider key found"):
        load_config(cli_provider=None, cli_model=None, cli_user_context=None)


def test_custom_provider_three_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(MissingProviderKeyError, match="ROADMODEL_API_KEY is not set"):
        load_config(cli_provider="custom", cli_model=None, cli_user_context=None)
    monkeypatch.setenv("ROADMODEL_API_KEY", "k")
    with pytest.raises(MissingProviderKeyError, match="ROADMODEL_MODEL"):
        load_config(cli_provider="custom", cli_model=None, cli_user_context=None)
    monkeypatch.setenv("ROADMODEL_MODEL", "local-model")
    with pytest.raises(MissingProviderKeyError, match="ROADMODEL_BASE_URL is not set"):
        load_config(cli_provider="custom", cli_model=None, cli_user_context=None)
    monkeypatch.setenv("ROADMODEL_BASE_URL", "http://localhost:8000/v1")
    cfg = load_config(cli_provider="custom", cli_model=None, cli_user_context=None)
    assert (cfg.provider, cfg.model, cfg.api_key) == ("custom", "local-model", "k")


def test_custom_key_from_config_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    toml = tmp_path / "xdg" / "roadmodel" / "config.toml"
    toml.parent.mkdir(parents=True)
    toml.write_text('[providers.custom]\napi_key = "from-toml"\n', encoding="utf-8")
    monkeypatch.setenv("ROADMODEL_BASE_URL", "http://localhost:8000/v1")
    cfg = load_config(cli_provider="custom", cli_model="m", cli_user_context=None)
    assert cfg.api_key == "from-toml"


def test_invalid_provider_lists_choices(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(MissingProviderKeyError) as excinfo:
        load_config(cli_provider="bedrock", cli_model=None, cli_user_context=None)
    assert "deepseek" in str(excinfo.value) and "custom" in str(excinfo.value)


def test_native_three_still_win_auto_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing behavior: with an OpenAI key AND a DeepSeek key present and no
    explicit provider, OpenAI is selected (native providers lead PROVIDER_ORDER)."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    cfg = load_config(cli_provider=None, cli_model=None, cli_user_context=None)
    assert (cfg.provider, cfg.api_key, cfg.model) == ("openai", "o", None)
