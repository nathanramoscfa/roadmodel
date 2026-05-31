# service/tests/test_recommend_endpoint.py
from __future__ import annotations

import importlib
import inspect
import sys
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from roadmodel.errors import MalformedResponseError  # type: ignore[import-untyped]

_MODULES_TO_RESET = (
    "app.main",
    "app.recommend",
)

_RECOMMEND_DICT: dict[str, Any] = {
    "model": "Claude Sonnet 4.6",
    "platform": "Claude Code",
    "settings": {"effort": "High", "thinking": "On"},
    "rationale": "Best for coding tasks.",
    "conversation": "New",
    "session_cost_estimate": None,
    "comparison_table": None,
}


def _load_main_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_main = _load_main_module(monkeypatch)
    return TestClient(app_main.app)


def _request_payload(task_description: str = "pick a model") -> dict[str, Any]:
    return {"task_description": task_description}


def test_healthz_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.version", lambda _: "0.2.0")

    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "roadmodel_version"}
    assert body["status"] == "ok"
    assert body["roadmodel_version"] == "0.2.0"


def test_recommend_returns_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")
    call_args: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        call_args["prompt"] = prompt
        call_args["config_provider"] = config.provider
        call_args["input_tokens"] = input_tokens
        call_args["output_tokens"] = output_tokens
        call_args["max_mode"] = max_mode
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert call_args == {
        "prompt": "pick a model",
        "config_provider": "anthropic",
        "input_tokens": None,
        "output_tokens": None,
        "max_mode": False,
    }
    assert body == {
        "model": "Claude Sonnet 4.6",
        "platform": "Claude Code",
        "settings": {"effort": "High", "thinking": "On"},
        "session_cost_estimate": None,
        "comparison_table": [],
    }


def test_recommend_input_length_cap(client: TestClient) -> None:
    response = client.post(
        "/v1/recommend",
        json=_request_payload(task_description="a" * 20001),
    )

    assert response.status_code == 422


def test_response_schema_matches_phase2_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        del prompt, config, input_tokens, output_tokens, max_mode
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "model",
        "platform",
        "settings",
        "session_cost_estimate",
        "comparison_table",
    }


def test_recommend_falls_back_to_next_provider_on_malformed_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #133: a parser failure (MalformedResponseError) on the primary
    provider must fall through to the next provider in the chain instead of
    leaking a 500. Mirrors the 2026-05-31 incident shape where the primary's
    response failed the regex while a fallback could still succeed."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    attempted: list[str] = []

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        attempted.append(config.provider)
        if config.provider == "anthropic":
            raise MalformedResponseError("ORCHESTRATION: Ultracode\n<unparseable for old regex>")
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    # Primary (anthropic) raised MalformedResponseError; loop fell through to
    # google, which succeeded.
    assert attempted == ["anthropic", "google"]
    assert response.json()["model"] == _RECOMMEND_DICT["model"]


def test_recommend_attempts_all_providers_then_raises_when_all_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #133: when EVERY provider returns an unparseable response (the
    actual 2026-05-31 incident shape — both Gemini and Haiku followed the new
    schema the old regex rejected), the fallback loop must attempt every
    provider and then re-raise MalformedResponseError rather than swallow it.
    The service has no HTTP error mapping, so this surfaces as the same
    unhandled 500 as the pre-existing all-providers-failed path — the drift
    guard (issue #134) is what stops whole-chain schema drift from shipping.
    Tested at the function level since the loop, not the HTTP layer, owns this
    behavior."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    attempted: list[str] = []

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        attempted.append(config.provider)
        raise MalformedResponseError("<unparseable>")

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    request = recommend_module.RecommendRequest(task_description="pick a model")
    with pytest.raises(MalformedResponseError):
        recommend_module.recommend(request)

    # Every provider in the chain was attempted before the loop re-raised.
    assert attempted == ["anthropic", "google"]


def test_fake_recommend_structured_matches_real_signature() -> None:
    """Contract guard per feedback_monkeypatched_contract_validation. The fakes
    in this file assume recommend_structured(prompt, config, *, input_tokens,
    output_tokens, max_mode, max_output_tokens). If the real signature drifts,
    every fake silently diverges and the first live call 500s — exactly the
    Phase 3 Step 3 failure mode. Pin the real contract the fakes are written
    against."""
    from roadmodel.recommend import recommend_structured as real  # type: ignore[import-untyped]

    params = inspect.signature(real).parameters
    assert list(params) == [
        "prompt",
        "config",
        "input_tokens",
        "output_tokens",
        "max_mode",
        "max_output_tokens",
    ]
    # Everything after `config` is keyword-only (declared after the bare *).
    assert params["input_tokens"].kind is inspect.Parameter.KEYWORD_ONLY
