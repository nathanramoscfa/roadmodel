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

# An output-contract-v2 stub: only the four always-on fields plus the dials a
# reasoning surface exposes. The provider adapters are contract-agnostic — they
# return the raw text and never parse it — so the minimal shape is the honest
# stub, and it doubles as proof that no adapter has quietly grown a dependency
# on the v1 "MAX MODE is always present" assumption.
_RECOMMENDER_RESPONSE = (
    "MODEL: x\nPLATFORM: y\nEFFORT: Low\nTHINKING: Off\nCONVERSATION: New\nRATIONALE: stub\n"
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
    google_provider.recommend("prompt", "system", api_key="key", max_output_tokens=1024)
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


def test_google_forwards_thinking_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #132: Gemini Flash reasons by default and that reasoning is decoded
    before (and against the budget of) the visible answer. thinking_budget must
    reach the SDK as config.thinking_config.thinking_budget."""
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key", thinking_budget=512)
    config = _FakeGoogleClient.captured["config"]
    assert config["thinking_config"] == {"thinking_budget": 512}


def test_google_forwards_thinking_budget_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """The critical case: thinking_budget=0 disables thinking. Because 0 is
    falsy, a truthiness guard would silently drop it and leave thinking on —
    exactly the bug that would make the latency fix a no-op. Pin that 0 is
    forwarded, not swallowed."""
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key", thinking_budget=0)
    config = _FakeGoogleClient.captured["config"]
    assert config["thinking_config"] == {"thinking_budget": 0}


def test_google_omits_thinking_config_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key")
    config = _FakeGoogleClient.captured["config"]
    assert "thinking_config" not in config


def test_google_forwards_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #176: without an explicit temperature Gemini samples at its default
    (~1.0), so the same task returns different model picks run-to-run.
    temperature must reach the SDK as config.temperature."""
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key", temperature=0.3)
    config = _FakeGoogleClient.captured["config"]
    assert config["temperature"] == 0.3


def test_google_forwards_temperature_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.0 (greedy/deterministic) is the intended recommender default. Because
    0.0 is falsy, a truthiness guard would silently drop it — pin that it is
    forwarded, not swallowed (mirrors the thinking_budget=0 guard)."""
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key", temperature=0.0)
    config = _FakeGoogleClient.captured["config"]
    assert config["temperature"] == 0.0


def test_google_omits_temperature_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fake(monkeypatch)
    google_provider.recommend("prompt", "system", api_key="key")
    config = _FakeGoogleClient.captured["config"]
    assert "temperature" not in config


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
    anthropic_provider.recommend("prompt", "system", api_key="key", max_output_tokens=1024)
    assert _FakeAnthropicClient.captured["max_tokens"] == 1024


def test_anthropic_keeps_4096_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_anthropic_fake(monkeypatch)
    anthropic_provider.recommend("prompt", "system", api_key="key")
    assert _FakeAnthropicClient.captured["max_tokens"] == 4096


def test_anthropic_ignores_thinking_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """thinking_budget is Gemini-specific (issue #132). Anthropic accepts the
    keyword for ProviderAdapter parity but must NOT forward it to the SDK —
    Anthropic extended-thinking has different semantics and the recommender
    response shape does not tolerate small caps on Anthropic (PR #128)."""
    _install_anthropic_fake(monkeypatch)
    anthropic_provider.recommend("prompt", "system", api_key="key", thinking_budget=0)
    captured = _FakeAnthropicClient.captured
    assert "thinking_budget" not in captured
    assert "thinking" not in captured
    assert "thinking_config" not in captured


def test_anthropic_ignores_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """temperature is a Gemini-specific knob (#176). Anthropic accepts it for
    ProviderAdapter parity but must NOT forward it to the SDK."""
    _install_anthropic_fake(monkeypatch)
    anthropic_provider.recommend("prompt", "system", api_key="key", temperature=0.0)
    assert "temperature" not in _FakeAnthropicClient.captured


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
    openai_provider.recommend("prompt", "system", api_key="key", max_output_tokens=1024)
    assert _FakeOpenAIClient.captured["max_output_tokens"] == 1024


def test_openai_omits_max_output_tokens_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_openai_fake(monkeypatch)
    openai_provider.recommend("prompt", "system", api_key="key")
    assert "max_output_tokens" not in _FakeOpenAIClient.captured


def test_openai_maps_thinking_budget_to_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gpt-5* reasoning models count reasoning tokens against max_output_tokens,
    so the provider MUST cap reasoning via reasoning.effort — otherwise the
    reasoning consumes the whole budget and returns no text (observed:
    gpt-5-mini 32s, empty). thinking_budget maps 0 -> minimal (anon), else low.
    The Gemini-specific keys (thinking_budget / thinking_config) are never sent."""
    _install_openai_fake(monkeypatch)
    openai_provider.recommend("p", "s", api_key="k", model="gpt-5-mini", thinking_budget=0)
    assert _FakeOpenAIClient.captured["reasoning"] == {"effort": "minimal"}
    assert "thinking_budget" not in _FakeOpenAIClient.captured
    assert "thinking_config" not in _FakeOpenAIClient.captured

    openai_provider.recommend("p", "s", api_key="k", model="gpt-5-mini", thinking_budget=None)
    assert _FakeOpenAIClient.captured["reasoning"] == {"effort": "low"}


def test_openai_no_reasoning_for_non_gpt5_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only gpt-5* models get the reasoning.effort cap; a non-reasoning model is
    left untouched (no reasoning key)."""
    _install_openai_fake(monkeypatch)
    openai_provider.recommend("p", "s", api_key="k", model="gpt-4o", thinking_budget=0)
    assert "reasoning" not in _FakeOpenAIClient.captured


def test_openai_ignores_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """temperature is a Gemini-specific knob (#176). OpenAI accepts it for
    ProviderAdapter parity but must NOT forward it to the SDK."""
    _install_openai_fake(monkeypatch)
    openai_provider.recommend("prompt", "system", api_key="key", temperature=0.0)
    assert "temperature" not in _FakeOpenAIClient.captured


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


@pytest.mark.parametrize(
    "module",
    [google_provider, anthropic_provider, openai_provider],
    ids=["google", "anthropic", "openai"],
)
def test_provider_signature_accepts_thinking_budget(
    module: ProviderAdapter,
) -> None:
    """Drift guard for the issue #132 thinking_budget keyword. Every provider
    must accept it as a keyword-only, default-None parameter (Gemini forwards
    it; Anthropic/OpenAI accept-and-ignore for ProviderAdapter parity) so the
    monkey-patched fixtures above cannot silently diverge from the real
    adapters. Mirrors the max_output_tokens guard."""
    sig = inspect.signature(module.recommend)
    assert "thinking_budget" in sig.parameters
    param = sig.parameters["thinking_budget"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


@pytest.mark.parametrize(
    "module",
    [google_provider, anthropic_provider, openai_provider],
    ids=["google", "anthropic", "openai"],
)
def test_provider_signature_accepts_temperature(
    module: ProviderAdapter,
) -> None:
    """Drift guard for the issue #176 temperature keyword. Every provider must
    accept it as a keyword-only, default-None parameter (Gemini forwards it;
    Anthropic/OpenAI accept-and-ignore for ProviderAdapter parity)."""
    sig = inspect.signature(module.recommend)
    assert "temperature" in sig.parameters
    param = sig.parameters["temperature"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None
