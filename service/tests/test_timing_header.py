# service/tests/test_timing_header.py
"""Phase 4 Step 7 — X-Roadmodel-Timing response header coverage.

The web tier in web/app/api/recommend/route.ts decomposes its
opaque provider_ms span by ingesting this header. The contract:

    X-Roadmodel-Timing: service_scoring_ms=<int>;service_provider_ms=<int>

This module asserts the header is (a) present on the happy path
and (b) parseable into the documented key/value pairs with
non-negative integer values whose sum approximates the request's
total wall-clock time on the service side.
"""

from __future__ import annotations

import importlib
import sys
import time
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

_MODULES_TO_RESET = (
    "app.main",
    "app.recommend",
)

_RECOMMEND_DICT: dict[str, Any] = {
    "model": "Gemini 2.5 Flash",
    "platform": "Google Gemini",
    "settings": {"effort": "Low", "thinking": "Off"},
    "rationale": "Cheapest qualifying knowledge-B engine.",
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


def _parse_timing(header_value: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for chunk in header_value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        out[key.strip()] = int(value.strip())
    return out


def test_timing_header_present_on_recommend(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake_recommend_structured(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        # Sleep long enough that the timer captures a non-zero
        # service_provider_ms value. 5ms is well above the
        # resolution of time.perf_counter and well below the
        # FastAPI testclient's own request overhead.
        time.sleep(0.005)
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(
        recommend_module,
        "recommend_structured",
        _fake_recommend_structured,
    )

    response = client.post("/v1/recommend", json={"task_description": "hi"})

    assert response.status_code == 200
    assert "X-Roadmodel-Timing" in response.headers, (
        f"missing X-Roadmodel-Timing header; got {dict(response.headers)}"
    )

    parsed = _parse_timing(response.headers["X-Roadmodel-Timing"])
    assert set(parsed.keys()) == {"service_scoring_ms", "service_provider_ms"}, (
        f"unexpected timing keys: {sorted(parsed.keys())}"
    )
    assert parsed["service_provider_ms"] >= 0
    assert parsed["service_scoring_ms"] >= 0
    # The provider span captured the sleep — must be at least 5ms.
    assert parsed["service_provider_ms"] >= 5, (
        f"service_provider_ms must reflect the 5ms sleep; got {parsed}"
    )
