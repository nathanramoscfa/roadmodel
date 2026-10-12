"""Request and diagnostic boundaries, using synthetic keys and no providers."""

from __future__ import annotations

import importlib
import io
import json
import logging
import queue
import secrets
import time
import warnings
from logging.handlers import QueueHandler
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models import RecommendRequest
from app.score import ScoreRequest


@pytest.mark.parametrize(
    "context",
    [
        {"unexpected": "private text"},
        {"subscriptions": ["one"] * 65},
        {"platforms_allowed": ["private\ntext"]},
        {"unavailable_models": [123]},
        {"availability_authoritative": "false"},
        {"classification": "arbitrary/high"},
        {"force_provider": "x" * 129},
        {"budget_priority": "arbitrary"},
    ],
)
def test_context_is_closed_and_bounded(context: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RecommendRequest(task_description="test", context=context)


def _pool() -> dict[str, Any]:
    return dict(
        pool="openrouter:credits",
        state="exhausted",
        observed_at=time.time() - 10,
        resets_at=None,
        used_percent=100,
        window_minutes=0,
    )


@pytest.mark.parametrize(
    "patch", [{"private": "text"}, {"used_percent": True}, {"source": "other"}, {"resets_at": 123}]
)
def test_pool_rows_are_closed(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScoreRequest(category="coding", complexity="low", pool_states=[{**_pool(), **patch}])


@pytest.mark.parametrize(
    "patch",
    [
        {"novel": 1},
        {"availability_authoritative": "false"},
        {"input_tokens": 10000001},
        {"input_tokens": True},
    ],
)
def test_score_types_are_strict(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(dict(category="coding", complexity="low", **patch))


def test_validation_does_not_reflect_private_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", "test-internal-token")
    app = importlib.import_module("app.main").app
    marker = secrets.token_hex(24)
    client = TestClient(app)
    response = client.post(
        "/v1/score",
        json={"category": marker},
        headers={"Authorization": "Bearer test-internal-token"},
    )
    assert response.status_code == 422
    assert marker not in response.text
    assert response.json() == {"error": "invalid_request"}


def test_oversized_body_rejected_before_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", "test-internal-token")
    client = TestClient(importlib.import_module("app.main").app)
    response = client.post(
        "/v1/score", content=b"x" * (1048576 + 1), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_structured_records_clean_before_queue() -> None:
    visitor = importlib.import_module("app.visitor")
    visitor.install_redaction()
    marker = secrets.token_hex(24)
    token = visitor._VISITOR_KEY.set(marker)
    records: queue.Queue[logging.LogRecord] = queue.Queue()
    logger = logging.getLogger("security.synthetic.queue")
    handler = QueueHandler(records)
    logger.addHandler(handler)
    try:
        logger.warning(
            "count=%d", 2, extra={"nested": {"value": [marker]}, "_visitor_scrubbed": True}
        )
    finally:
        logger.removeHandler(handler)
        visitor._VISITOR_KEY.reset(token)
    record = records.get_nowait()
    assert record.getMessage() == "count=2"
    assert marker not in json.dumps(record.__dict__, default=str)


def test_warning_sanitized_before_registry() -> None:
    visitor = importlib.import_module("app.visitor")
    visitor.install_redaction()
    marker = secrets.token_hex(24)
    token = visitor._VISITOR_KEY.set(marker)
    registry: dict[Any, Any] = {}
    output = io.StringIO()
    try:
        warnings.warn_explicit(marker, UserWarning, "synthetic.py", 1, registry=registry)
        warnings.showwarning(UserWarning(marker), UserWarning, marker, 1, file=output)
    finally:
        visitor._VISITOR_KEY.reset(token)
    assert marker not in repr(registry)
    assert marker not in output.getvalue()
