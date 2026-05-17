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
    "app.auth",
    "app.recommend",
)
_AUTH_BEARER = "internal-test-secret"


class _FakeEstimate:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return dict(self._payload)


class _FakeStructuredRecommendation:
    def __init__(self) -> None:
        self.model = "Claude Sonnet 4.6"
        self.platform = "Claude Code"
        self.settings = {"effort": "High", "thinking": "On"}
        self.session_cost_estimate = _FakeEstimate(
            {
                "model_id": "claude-sonnet-4-6",
                "platform_id": "claude-code",
                "total_usd": 0.00123,
                "funding_source": "per-token",
            }
        )
        self.comparison_table = [
            _FakeEstimate(
                {
                    "model_id": "claude-sonnet-4-6",
                    "platform_id": "claude-code",
                    "total_usd": 0.00123,
                    "funding_source": "per-token",
                }
            ),
            _FakeEstimate(
                {
                    "model_id": "gpt-5-3-codex",
                    "platform_id": "codex",
                    "total_usd": 0.00198,
                    "funding_source": "per-token",
                }
            ),
        ]


def _load_main_module(
    monkeypatch: pytest.MonkeyPatch,
    token: str = _AUTH_BEARER,
) -> ModuleType:
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", token)
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_main = _load_main_module(monkeypatch)
    return TestClient(app_main.app)


def _request_payload(task_description: str = "pick a model") -> dict[str, Any]:
    return {
        "task_description": task_description,
        "context": {"team": "platform", "deadline": "today"},
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_healthz_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.version", lambda _: "0.2.0")

    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "roadmodel_version"}
    assert body["status"] == "ok"
    assert body["roadmodel_version"] == "0.2.0"


def test_recommend_requires_bearer(client: TestClient) -> None:
    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_or_missing_bearer"


def test_recommend_rejects_bad_bearer(client: TestClient) -> None:
    response = client.post(
        "/v1/recommend",
        json=_request_payload(),
        headers=_auth_headers("wrong-token"),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_or_missing_bearer"


def test_recommend_accepts_good_bearer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")
    call_args: dict[str, Any] = {}

    def _fake_recommend_structured(
        task_description: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> _FakeStructuredRecommendation:
        call_args["task_description"] = task_description
        call_args["context"] = context
        return _FakeStructuredRecommendation()

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post(
        "/v1/recommend",
        json=_request_payload(),
        headers=_auth_headers(_AUTH_BEARER),
    )

    assert response.status_code == 200
    body = response.json()
    assert call_args == {
        "task_description": "pick a model",
        "context": {"team": "platform", "deadline": "today"},
    }
    assert body == {
        "model": "Claude Sonnet 4.6",
        "platform": "Claude Code",
        "settings": {"effort": "High", "thinking": "On"},
        "session_cost_estimate": {
            "model_id": "claude-sonnet-4-6",
            "platform_id": "claude-code",
            "total_usd": 0.00123,
            "funding_source": "per-token",
        },
        "comparison_table": [
            {
                "model_id": "claude-sonnet-4-6",
                "platform_id": "claude-code",
                "total_usd": 0.00123,
                "funding_source": "per-token",
            },
            {
                "model_id": "gpt-5-3-codex",
                "platform_id": "codex",
                "total_usd": 0.00198,
                "funding_source": "per-token",
            },
        ],
        "free_tier_label": None,
    }


def test_recommend_input_length_cap(client: TestClient) -> None:
    response = client.post(
        "/v1/recommend",
        json=_request_payload(task_description="a" * 20001),
        headers=_auth_headers(_AUTH_BEARER),
    )

    assert response.status_code == 422


def test_response_schema_matches_phase2_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake_recommend_structured(
        task_description: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> _FakeStructuredRecommendation:
        del task_description, context
        return _FakeStructuredRecommendation()

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post(
        "/v1/recommend",
        json=_request_payload(),
        headers=_auth_headers(_AUTH_BEARER),
    )

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "model",
        "platform",
        "settings",
        "session_cost_estimate",
        "comparison_table",
        "free_tier_label",
    }
