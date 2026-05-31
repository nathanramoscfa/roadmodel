# service/tests/test_recommend_endpoint.py
from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
