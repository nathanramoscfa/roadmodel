"""Tests for the optional max_output_tokens parameter on every provider
adapter (Phase 4 Step 7b).

Each provider's `recommend(...)` must:
- accept a `max_output_tokens: int | None = None` keyword,
- forward the value to its SDK when set,
- preserve prior behavior when unset.

Per memory `feedback_monkeypatched_contract_validation`, the suite
includes an `inspect.signature` check against each provider's
`recommend` so a future signature drift fails loudly rather than
allowing the monkey-patched fixtures to silently diverge from the
real adapter.
"""

from __future__ import annotations

import inspect
import sys
import types
from typing import Any

import pytest

from roadmodel.providers import ProviderAdapter
from roadmodel.providers import anthropic as anthropic_provider
from roadmodel.providers import google as google_provider
from roadmodel.providers import openai as openai_provider

_RECOMMENDER_RESPONSE = (
    "MODEL: x\n"
    "PLATFORM: y\n"
    "MAX MODE: Off\n"
    "THINKING: Off\n"
    "CONVERSATION: New\n"
    "RATIONALE: stub\n"
)


# --------------------------------------------------------------------- google


class _FakeGoogleClient:
    captured: dict[str, Any] = {}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeGoogleModels()


class _FakeGoogleModels:
    def generate_content(self, **kwargs: Any) -> Any:
        _FakeGoogleClient.captured = dict(kwargs)
        return types.SimpleNamespace(text=_RECOMMENDER_RESPONSE)


def _install_google_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeGoogleClient.captured = {}
    fake_genai = types.ModuleType("google.genai")
    fake_errors = types.ModuleType("google.genai.errors")

    class _FakeAPIError(Exception):
        pass

    fake_errors.APIError = _FakeAPIError  # type: ignore[attr-defined]
    fake_genai.Client = _FakeGoogleClient  # type: ignore[attr-defined]
    fake_genai.errors = fake_errors  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.errors", fake_errors)


def test_google_forwards_max_output_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fake(monkeypatch)
    google_provider.recommend(
        "prompt", "system", api_key="key", max_output_tokens=1024
    )
    config = _FakeGoogleClient.captured["config"]
    assert config["max_output_tokens"] == 1024
    assert config["system_instruction"] == "system"


def test_google_omits_max_output_tokens_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key")
    config = _FakeGoogleClient.captured["config"]
    assert "max_output_tokens" not in config


# ------------------------------------------------------------------ anthropic


class _FakeAnthropicClient:
    captured: dict[str, Any] = {}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = _FakeAnthropicMessages()


class _FakeAnthropicMessages:
    def create(self, **kwargs: Any) -> Any:
        _FakeAnthropicClient.captured = dict(kwargs)
        block = types.SimpleNamespace(type="text", text=_RECOMMENDER_RESPONSE)
        return types.SimpleNamespace(content=[block])


def _install_anthropic_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAnthropicClient.captured = {}
    fake_anthropic = types.ModuleType("anthropic")

    class _FakeAPIError(Exception):
        pass

    fake_anthropic.Anthropic = _FakeAnthropicClient  # type: ignore[attr-defined]
    fake_anthropic.APIError = _FakeAPIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)


def test_anthropic_forwards_max_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_anthropic_fake(monkeypatch)
    anthropic_provider.recommend(
        "prompt", "system", api_key="key", max_output_tokens=1024
    )
    assert _FakeAnthropicClient.captured["max_tokens"] == 1024


def test_anthropic_keeps_4096_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_anthropic_fake(monkeypatch)
    anthropic_provider.recommend("prompt", "system", api_key="key")
    assert _FakeAnthropicClient.captured["max_tokens"] == 4096


# --------------------------------------------------------------------- openai


class _FakeOpenAIClient:
    captured: dict[str, Any] = {}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.responses = _FakeOpenAIResponses()


class _FakeOpenAIResponses:
    def create(self, **kwargs: Any) -> Any:
        _FakeOpenAIClient.captured = dict(kwargs)
        return types.SimpleNamespace(output_text=_RECOMMENDER_RESPONSE)


def _install_openai_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeOpenAIClient.captured = {}
    fake_openai = types.ModuleType("openai")

    class _FakeAPIError(Exception):
        pass

    fake_openai.OpenAI = _FakeOpenAIClient  # type: ignore[attr-defined]
    fake_openai.APIError = _FakeAPIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)


def test_openai_forwards_max_output_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_openai_fake(monkeypatch)
    openai_provider.recommend(
        "prompt", "system", api_key="key", max_output_tokens=1024
    )
    assert _FakeOpenAIClient.captured["max_output_tokens"] == 1024


def test_openai_omits_max_output_tokens_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_openai_fake(monkeypatch)
    openai_provider.recommend("prompt", "system", api_key="key")
    assert "max_output_tokens" not in _FakeOpenAIClient.captured


# ---------------------------------------------- contract validation (drift guard)


@pytest.mark.parametrize(
    "module",
    [google_provider, anthropic_provider, openai_provider],
    ids=["google", "anthropic", "openai"],
)
def test_provider_signature_accepts_max_output_tokens(
    module: ProviderAdapter,
) -> None:
    """Drift guard per [[feedback-monkeypatched-contract-validation]].

    If a future refactor renames or removes the keyword, the monkey-
    patched fixtures above would silently pass (they only capture
    whatever kwargs the real call forwards). This signature check
    fails loudly in that scenario before the live adapter ever runs.
    """
    sig = inspect.signature(module.recommend)
    assert "max_output_tokens" in sig.parameters
    param = sig.parameters["max_output_tokens"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None
