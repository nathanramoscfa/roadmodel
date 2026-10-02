"""Engine-call behavior the recommender's engine menu depends on.

Two things are pinned here:

1. Each adapter runs every engine it can reach at the intended low-latency
   setting: the gpt-6 line gets the same reasoning.effort cap as gpt-5, Gemini 3
   gets a thinking LEVEL instead of the 2.5 token budget, and Claude gets a
   cached system prompt, effort `low`, and no sampling parameter on the models
   that reject one.
2. Each adapter reports the tokens the provider actually billed to
   roadmodel.usage, so the hosted service can meter a call exactly (cached
   input included) instead of estimating it.

The fakes mirror the SDK response shapes field for field (usage blocks
included); the signature drift guard in test_provider_max_output_tokens.py
covers the adapters' keyword contract.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from roadmodel import usage
from roadmodel.providers import anthropic as anthropic_provider
from roadmodel.providers import google as google_provider
from roadmodel.providers import openai as openai_provider
from roadmodel.providers.openai_compatible import ADAPTERS as COMPATIBLE_ADAPTERS

_TEXT = "MODEL: x\nPLATFORM: y\nEFFORT: Low\nTHINKING: Off\nCONVERSATION: New\nRATIONALE: stub\n"


@pytest.fixture(autouse=True)
def _fresh_usage() -> None:
    usage.reset()


# --------------------------------------------------------------------- openai


class _OpenAIFake:
    captured: dict[str, Any] = {}
    response_usage: Any = None

    def __init__(self, api_key: str) -> None:
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        _OpenAIFake.captured = dict(kwargs)
        return types.SimpleNamespace(output_text=_TEXT, usage=_OpenAIFake.response_usage)


def _install_openai(monkeypatch: pytest.MonkeyPatch, response_usage: Any = None) -> None:
    _OpenAIFake.captured = {}
    _OpenAIFake.response_usage = response_usage
    mod = types.ModuleType("openai")

    class _APIError(Exception):
        pass

    mod.OpenAI = _OpenAIFake  # type: ignore[attr-defined]
    mod.APIError = _APIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", mod)


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
def test_openai_gpt6_gets_the_reasoning_cap(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    """The gpt-6 line bills reasoning against max_output_tokens like gpt-5, and
    has no `minimal` rung: the floor is `low`."""
    _install_openai(monkeypatch)
    openai_provider.recommend("p", "s", api_key="k", model=model, thinking_budget=0)
    assert _OpenAIFake.captured["reasoning"] == {"effort": "low"}


def test_openai_records_usage_with_cached_and_reasoning_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_openai(
        monkeypatch,
        types.SimpleNamespace(
            input_tokens=60929,
            input_tokens_details=types.SimpleNamespace(cached_tokens=60926),
            output_tokens=716,
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=330),
        ),
    )
    openai_provider.recommend("p", "s", api_key="k", model="gpt-5.6-luna", thinking_budget=0)
    got = usage.last()
    assert got is not None
    assert (got.provider, got.model) == ("openai", "gpt-5.6-luna")
    assert (got.input_tokens, got.cached_input_tokens, got.output_tokens) == (60929, 60926, 716)
    assert got.reasoning_tokens == 330
    assert got.cache_write_tokens == 0


def test_openai_without_a_usage_block_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_openai(monkeypatch, None)
    assert openai_provider.recommend("p", "s", api_key="k", model="gpt-5.6-luna")
    assert usage.last() is None


# --------------------------------------------------------------------- google


class _GoogleFake:
    captured: dict[str, Any] = {}
    usage_metadata: Any = None

    def __init__(self, api_key: str) -> None:
        self.models = self

    def generate_content(self, **kwargs: Any) -> Any:
        _GoogleFake.captured = dict(kwargs)
        return types.SimpleNamespace(text=_TEXT, usage_metadata=_GoogleFake.usage_metadata)


def _install_google(monkeypatch: pytest.MonkeyPatch, usage_metadata: Any = None) -> None:
    _GoogleFake.captured = {}
    _GoogleFake.usage_metadata = usage_metadata
    genai = types.ModuleType("google.genai")
    errors = types.ModuleType("google.genai.errors")

    class _APIError(Exception):
        pass

    errors.APIError = _APIError  # type: ignore[attr-defined]
    genai.Client = _GoogleFake  # type: ignore[attr-defined]
    genai.errors = errors  # type: ignore[attr-defined]
    google = types.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors)


@pytest.mark.parametrize(
    ("budget", "level"), [(0, "low"), (512, "low"), (4096, "medium"), (24576, "high")]
)
def test_gemini3_gets_a_thinking_level(
    monkeypatch: pytest.MonkeyPatch, budget: int, level: str
) -> None:
    """Gemini 3+ documents discrete levels, not a token budget; `low` is the
    floor every Gemini 3 model accepts (3.8 Flash has no `minimal`)."""
    _install_google(monkeypatch)
    google_provider.recommend(
        "p", "s", api_key="k", model="gemini-3.8-flash", thinking_budget=budget
    )
    assert _GoogleFake.captured["config"]["thinking_config"] == {"thinking_level": level}


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-2.5-pro"])
def test_gemini25_keeps_the_numeric_budget(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    _install_google(monkeypatch)
    google_provider.recommend("p", "s", api_key="k", model=model, thinking_budget=0)
    assert _GoogleFake.captured["config"]["thinking_config"] == {"thinking_budget": 0}


def test_google_records_usage_with_thoughts_as_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google(
        monkeypatch,
        types.SimpleNamespace(
            prompt_token_count=61000,
            cached_content_token_count=58000,
            candidates_token_count=650,
            thoughts_token_count=200,
        ),
    )
    google_provider.recommend("p", "s", api_key="k", model="gemini-3.8-flash", thinking_budget=0)
    got = usage.last()
    assert got is not None
    assert (got.input_tokens, got.cached_input_tokens, got.output_tokens) == (61000, 58000, 850)
    assert got.reasoning_tokens == 200


# ------------------------------------------------------------------ anthropic


class _AnthropicFake:
    captured: dict[str, Any] = {}
    response_usage: Any = None

    def __init__(self, api_key: str) -> None:
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        _AnthropicFake.captured = dict(kwargs)
        block = types.SimpleNamespace(type="text", text=_TEXT)
        return types.SimpleNamespace(content=[block], usage=_AnthropicFake.response_usage)


def _install_anthropic(monkeypatch: pytest.MonkeyPatch, response_usage: Any = None) -> None:
    _AnthropicFake.captured = {}
    _AnthropicFake.response_usage = response_usage
    mod = types.ModuleType("anthropic")

    class _APIError(Exception):
        pass

    mod.Anthropic = _AnthropicFake  # type: ignore[attr-defined]
    mod.APIError = _APIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def test_anthropic_caches_the_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_anthropic(monkeypatch)
    anthropic_provider.recommend("task", "SELECTOR", api_key="k", model="claude-sonnet-5")
    assert _AnthropicFake.captured["system"] == [
        {"type": "text", "text": "SELECTOR", "cache_control": {"type": "ephemeral"}}
    ]
    assert _AnthropicFake.captured["messages"] == [{"role": "user", "content": "task"}]


@pytest.mark.parametrize(
    "model", ["claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]
)
def test_anthropic_floor_is_low_effort(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    """Effort is the dial on current Claude models (Opus 5.5 cannot disable
    thinking at all); no thinking block and no sampling parameter is sent."""
    _install_anthropic(monkeypatch)
    anthropic_provider.recommend(
        "p", "s", api_key="k", model=model, thinking_budget=0, temperature=0.0
    )
    captured = _AnthropicFake.captured
    assert captured["output_config"] == {"effort": "low"}
    assert "thinking" not in captured
    assert "temperature" not in captured


def test_anthropic_haiku_takes_sampling_but_not_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_anthropic(monkeypatch)
    anthropic_provider.recommend(
        "p", "s", api_key="k", model="claude-haiku-4-5", thinking_budget=0, temperature=0.0
    )
    assert "output_config" not in _AnthropicFake.captured
    assert _AnthropicFake.captured["temperature"] == 0.0


def test_anthropic_unknown_model_gets_neither_dial(monkeypatch: pytest.MonkeyPatch) -> None:
    """An id the adapter cannot read is sent without effort or sampling, the
    side of a 400 that still answers."""
    _install_anthropic(monkeypatch)
    anthropic_provider.recommend(
        "p", "s", api_key="k", model="some-future-name", thinking_budget=0, temperature=0.0
    )
    assert "output_config" not in _AnthropicFake.captured
    assert "temperature" not in _AnthropicFake.captured


def test_anthropic_records_cache_reads_and_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_anthropic(
        monkeypatch,
        types.SimpleNamespace(
            input_tokens=40,
            cache_read_input_tokens=65000,
            cache_creation_input_tokens=0,
            output_tokens=900,
        ),
    )
    anthropic_provider.recommend("p", "s", api_key="k", model="claude-sonnet-5", thinking_budget=0)
    got = usage.last()
    assert got is not None
    assert (got.input_tokens, got.cached_input_tokens, got.cache_write_tokens) == (65040, 65000, 0)
    assert got.output_tokens == 900


# --------------------------------------------------- openai-compatible engines


class _ChatFake:
    def __init__(self, **kwargs: Any) -> None:
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=_TEXT)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=types.SimpleNamespace(
                prompt_tokens=61000,
                completion_tokens=800,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=59000),
            ),
        )


def test_compatible_adapter_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("openai")

    class _APIError(Exception):
        pass

    mod.OpenAI = _ChatFake  # type: ignore[attr-defined]
    mod.APIError = _APIError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", mod)
    adapter = COMPATIBLE_ADAPTERS["deepseek"]
    adapter.recommend("p", "s", api_key="k", model="deepseek-flash", thinking_budget=0)
    got = usage.last()
    assert got is not None
    assert (got.provider, got.input_tokens, got.cached_input_tokens) == ("deepseek", 61000, 59000)


# ------------------------------------------------------------------- usage API


def test_record_skips_non_integer_totals() -> None:
    usage.record("openai", "m", input_tokens=None, output_tokens=5)
    assert usage.last() is None
    usage.record("openai", "m", input_tokens=True, output_tokens=5)
    assert usage.last() is None


def test_reset_clears_the_previous_call() -> None:
    usage.record("openai", "m", input_tokens=10, output_tokens=5)
    assert usage.last() is not None
    usage.reset()
    assert usage.last() is None
