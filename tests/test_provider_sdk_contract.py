"""Every argument an adapter sends must exist in the INSTALLED provider SDK.

The other adapter tests replace each SDK with a fake that accepts anything, so
an argument a new SDK major drops passes them and then fails in production with
a TypeError before any request: anthropic 1.0 removed `temperature` from
messages.create, and every Claude engine fell through to the fallback chain.
CI installs the newest SDKs the `recommend` extra allows, so this test catches
such a break on the pull request that would ship it.
"""

from __future__ import annotations

import inspect
import sys
import types
from typing import Any

import pytest

from roadmodel.providers import anthropic as anthropic_provider
from roadmodel.providers import google as google_provider
from roadmodel.providers import openai as openai_provider

anthropic_sdk = pytest.importorskip("anthropic")
openai_sdk = pytest.importorskip("openai")
genai_sdk = pytest.importorskip("google.genai")
genai_types = pytest.importorskip("google.genai.types")

_TEXT = "MODEL: x\nPLATFORM: y\nCONVERSATION: New\nRATIONALE: stub\n"


def _params(method: Any) -> set[str]:
    sig = inspect.signature(method)
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()), (
        "the SDK method takes **kwargs; this contract check would prove nothing"
    )
    return set(sig.parameters)


ANTHROPIC_PARAMS = _params(anthropic_sdk.Anthropic(api_key="x").messages.create)
OPENAI_PARAMS = _params(openai_sdk.OpenAI(api_key="x").responses.create)
GOOGLE_PARAMS = _params(genai_sdk.Client(api_key="x").models.generate_content)


def _capture(monkeypatch: pytest.MonkeyPatch, module_name: str, build: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    fake = build(captured)
    monkeypatch.setitem(sys.modules, module_name, fake)
    return captured


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-sonnet-5-5", "claude-opus-5-5"])
def test_anthropic_arguments_exist_in_the_sdk(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, api_key: str) -> None:
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=_TEXT)])

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client  # type: ignore[attr-defined]
    mod.APIError = Exception  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    anthropic_provider.recommend(
        "p",
        "s",
        api_key="k",
        model=model,
        max_output_tokens=8192,
        thinking_budget=0,
        temperature=0.0,
    )
    assert set(captured) <= ANTHROPIC_PARAMS, set(captured) - ANTHROPIC_PARAMS


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-5-mini", "gpt-4o"])
def test_openai_arguments_exist_in_the_sdk(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, api_key: str) -> None:
            self.responses = self

        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return types.SimpleNamespace(output_text=_TEXT)

    mod = types.ModuleType("openai")
    mod.OpenAI = _Client  # type: ignore[attr-defined]
    mod.APIError = Exception  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", mod)
    openai_provider.recommend(
        "p",
        "s",
        api_key="k",
        model=model,
        max_output_tokens=6144,
        thinking_budget=0,
        temperature=0.0,
    )
    assert set(captured) <= OPENAI_PARAMS, set(captured) - OPENAI_PARAMS


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "gemini-2.5-flash"])
def test_google_arguments_and_config_exist_in_the_sdk(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, api_key: str) -> None:
            self.models = self

        def generate_content(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return types.SimpleNamespace(text=_TEXT)

    genai = types.ModuleType("google.genai")
    errors = types.ModuleType("google.genai.errors")
    errors.APIError = Exception  # type: ignore[attr-defined]
    genai.Client = _Client  # type: ignore[attr-defined]
    genai.errors = errors  # type: ignore[attr-defined]
    google = types.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors)
    google_provider.recommend(
        "p",
        "s",
        api_key="k",
        model=model,
        max_output_tokens=6144,
        thinking_budget=0,
        temperature=0.0,
    )
    assert set(captured) <= GOOGLE_PARAMS, set(captured) - GOOGLE_PARAMS
    # The config dict must validate as the SDK's own GenerateContentConfig.
    genai_types.GenerateContentConfig.model_validate(captured["config"])
