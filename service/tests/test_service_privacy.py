"""Streaming, diagnostic and admission tests with no outbound provider calls."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import secrets
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from app.models import RecommendRequest, RecommendResponse


@pytest.mark.parametrize("key", ["opaque-key-for-test", "s", "%", "d"])
def test_log_formatting_and_late_filters(key: str, capsys: pytest.CaptureFixture[str]) -> None:
    from app.redaction import _VISITOR_KEY, install_redaction

    install_redaction()
    captured: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    class Late(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.late = {key: key}
            return True

    logger = logging.getLogger("security.late.handler")
    handler = Capture()
    handler.addFilter(Late())
    logger.addHandler(handler)
    logger.propagate = False
    token = _VISITOR_KEY.set(key)
    try:
        logger.warning("%s %d", key, 7)
        logger.warning("%(value)s", {"value": key})
        logger.warning("%d", key)
    finally:
        _VISITOR_KEY.reset(token)
        logger.removeHandler(handler)
        logger.propagate = True
    assert captured[0].getMessage() == "[visitor-key] 7"
    assert captured[1].getMessage() == "[visitor-key]"
    assert captured[2].getMessage() == "[visitor-key]"
    assert all(record.__dict__["late"] == {"[visitor-key]": "[visitor-key]"} for record in captured)
    assert not capsys.readouterr().err


def test_warning_category_and_source_are_not_retained() -> None:
    from app.redaction import _VISITOR_KEY, install_redaction

    install_redaction()
    marker = secrets.token_hex(24)
    category = type(marker, (UserWarning,), {})
    token = _VISITOR_KEY.set(marker)
    registry: dict[Any, Any] = {}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn("ordinary", category, stacklevel=1)
            warnings.warn_explicit("ordinary", category, "synthetic.py", 1, registry=registry)
            warnings.warn("ordinary", UserWarning, stacklevel=1, source={"key": marker})
        assert len(caught) == 1
        assert caught[0].source is None
        assert marker not in repr(registry)
    finally:
        _VISITOR_KEY.reset(token)


def _asgi_probe(
    headers: list[tuple[bytes, bytes]], messages: list[Message], *, fail_after_start: bool = False
) -> tuple[list[Message], list[bytes]]:
    from app.boundaries import RequestBoundaries
    from app.redaction import _VISITOR_KEY

    sent: list[Message] = []
    bodies: list[bytes] = []
    scope: Scope = dict(type="http", method="POST", path="/synthetic", headers=headers)

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(scope: Any, receive: Any, send: Any) -> None:
        body = await receive()
        bodies.append(body["body"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if fail_after_start:
            raise RuntimeError(_VISITOR_KEY.get())
        await send({"type": "http.response.body", "body": b"ok"})

    asyncio.run(RequestBoundaries(app)(scope, receive, send))
    assert _VISITOR_KEY.get() is None
    return sent, bodies


@pytest.mark.parametrize(
    "headers,messages,status",
    [
        ([], [{"type": "http.request", "body": b"x" * 1048577}], 413),
        ([(b"content-length", b"1")], [{"type": "http.request", "body": b"xx"}], 400),
        ([(b"content-length", b"3")], [{"type": "http.request", "body": b"xx"}], 400),
        ([(b"content-length", b"0"), (b"content-length", b"0")], [], 400),
        ([(b"content-length", b"+1")], [], 400),
        ([(b"content-length", b"9" * 100)], [], 400),
        ([(b"content-encoding", b"gzip")], [], 415),
        ([(b"x-roadmodel-visitor-key", b"a"), (b"x-roadmodel-visitor-key", b"b")], [], 400),
        ([], [{"type": "http.request", "body": b"", "more_body": True}] * 129, 400),
    ],
)
def test_stream_boundaries(
    headers: list[tuple[bytes, bytes]], messages: list[Message], status: int
) -> None:
    sent, bodies = _asgi_probe(headers, list(messages))
    assert sent[0]["status"] == status
    assert not bodies


def test_disconnect_and_exact_body_limit() -> None:
    sent, bodies = _asgi_probe([], [{"type": "http.disconnect"}])
    assert not sent and not bodies
    sent, bodies = _asgi_probe(
        [],
        [
            {"type": "http.request", "body": b"x" * 1000000, "more_body": True},
            {"type": "http.request", "body": b"x" * 48576},
        ],
    )
    assert sent[0]["status"] == 200 and len(bodies[0]) == 1048576
    sent, _ = _asgi_probe(
        [(b"x-roadmodel-visitor-key", b"opaque-fixture")],
        [{"type": "http.request", "body": b""}],
        fail_after_start=True,
    )
    assert sum(message["type"] == "http.response.start" for message in sent) == 1


def test_ready_chunks_cannot_starve_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app import boundaries

    clock = iter([0.0, 0.0, 16.0])
    monkeypatch.setattr(boundaries, "time", SimpleNamespace(monotonic=lambda: next(clock, 16.0)))
    sent, bodies = _asgi_probe([], [{"type": "http.request", "body": b"x", "more_body": True}])
    assert sent[0]["status"] == 408 and not bodies


@pytest.mark.parametrize(
    "entry,callee",
    [("recommend", "recommend_structured"), ("recommend_ladder", "recommend_structured_ladder")],
)
def test_budget_stops_fallback(monkeypatch: pytest.MonkeyPatch, entry: str, callee: str) -> None:
    from types import SimpleNamespace

    from roadmodel.errors import ProviderCallError  # type: ignore[import-untyped]
    from roadmodel.providers._safety import hosted_timeout  # type: ignore[import-untyped]

    from app import budget

    module = importlib.import_module("app.recommend")
    signature = inspect.signature(getattr(module, callee))
    clock = [0.0]
    calls: list[float] = []

    def fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        signature.bind(*args, **kwargs)
        calls.append(hosted_timeout())
        clock[0] = 121.0
        raise ProviderCallError("synthetic failure")

    monkeypatch.setenv("OPENAI_API_KEY", "operator-fixture")
    monkeypatch.setenv("GOOGLE_API_KEY", "operator-fixture")
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, callee, fake)
    before = hosted_timeout()
    with pytest.raises(HTTPException) as error:
        getattr(module, entry)(RecommendRequest(task_description="fixture"))
    assert error.value.status_code == 504
    assert calls == [60.0]
    assert hosted_timeout() == before


def test_concurrent_request_context_and_reload(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.redaction import _VISITOR_KEY

    main = importlib.reload(importlib.import_module("app.main"))
    visitor = importlib.reload(importlib.import_module("app.visitor"))
    visitor.install_redaction()
    assert visitor._VISITOR_KEY is _VISITOR_KEY
    barrier = Barrier(2)
    keys = [secrets.token_hex(24), secrets.token_hex(24)]
    seen: list[str] = []

    def fake(req: RecommendRequest) -> RecommendResponse:
        barrier.wait(timeout=5)
        key = _VISITOR_KEY.get()
        assert key is not None
        seen.append(key)
        logging.getLogger("uvicorn.access").warning("request %s", key, extra={"nested": [key]})
        return RecommendResponse(model="fixture", platform="fixture", settings={})

    inspect.signature(main.recommend).bind(RecommendRequest(task_description="fixture"))
    monkeypatch.setattr(main, "recommend", fake)
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", "test-internal-token")

    def post(key: str) -> int:
        with TestClient(main.app) as client:
            return client.post(
                "/v1/recommend",
                json={"task_description": "fixture"},
                headers={
                    "Authorization": "Bearer test-internal-token",
                    "X-Roadmodel-Visitor-Key": key,
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(post, keys)) == [200, 200]
    assert sorted(seen) == sorted(keys)
    assert _VISITOR_KEY.get() is None
    rendered = repr([record.__dict__ for record in caplog.records])
    assert all(key not in rendered for key in keys)


def test_full_valid_context_and_unicode_preserve_semantics() -> None:
    from app.context import RecommendContext

    now = time.time() - 1
    context = dict(
        subscriptions=["claude-max"],
        api_providers=["openai"],
        allowed_jurisdictions=["us", "eu"],
        platforms_allowed=["Claude Code"],
        platforms_excluded=[],
        unavailable_models=["model-id"],
        availability_authoritative=True,
        budget_priority="balanced",
        consumption_headroom="auto",
        force_provider="openai-gpt-6-luna",
        classification="coding/high/novel",
        pool_states=[
            dict(
                pool="antigravity:all",
                state="headroom",
                observed_at=now,
                resets_at=None,
                used_percent=0,
                window_minutes=10080,
                source="antigravity",
                platform_id="antigravity",
            )
        ],
    )
    request = RecommendRequest.model_validate_json(
        json.dumps(dict(task_description="\U0001f600" * 50000, context=context), ensure_ascii=True)
    )
    assert request.context == context
    assert RecommendContext().model_dump(exclude_unset=True) == {}
    assert RecommendRequest(task_description="x").context is None


@pytest.mark.parametrize("key", ["before[visitor-key]after", "[visitor-key]"])
def test_literal_redaction_marker_cannot_hide_key(key: str) -> None:
    from app.redaction import _VISITOR_KEY, scrub

    token = _VISITOR_KEY.set(key)
    try:
        assert key not in scrub(key) or key == "[visitor-key]" and scrub(key) == "[redacted]"
    finally:
        _VISITOR_KEY.reset(token)


def test_failed_error_response_does_not_escape_key_context() -> None:
    from app.boundaries import RequestBoundaries
    from app.redaction import _VISITOR_KEY

    marker = secrets.token_hex(24)

    async def app(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError(marker)

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        raise OSError("disconnected")

    asyncio.run(
        RequestBoundaries(app)(
            dict(type="http", headers=[(b"x-roadmodel-visitor-key", marker.encode())]),
            receive,
            send,
        )
    )
    assert _VISITOR_KEY.get() is None


def test_warning_capture_toggle_has_no_recursive_sink(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import io

    from app.redaction import _VISITOR_KEY, install_redaction

    old_show = warnings.showwarning
    old_saved = getattr(logging, "_warnings_showwarning", None)
    marker = secrets.token_hex(24)
    token = _VISITOR_KEY.set(marker)
    try:
        logging.captureWarnings(True)
        install_redaction()
        warnings.showwarning("ordinary", UserWarning, "fixture", 1)
        assert any(record.name == "py.warnings" for record in caplog.records)
        with warnings.catch_warnings(record=True) as caught:
            logging.captureWarnings(False)
            logging.captureWarnings(True)
            output = io.StringIO()
            warnings.showwarning(marker, UserWarning, marker, 1, file=output)
            assert marker not in output.getvalue()
            retained = output.getvalue() + repr([(str(w.message), w.filename) for w in caught])
            assert marker not in retained
            assert "[visitor-key]" in retained
    finally:
        _VISITOR_KEY.reset(token)
        warnings.showwarning = old_show
        monkeypatch.setattr(logging, "_warnings_showwarning", old_saved)


def test_timeout_remaining_and_submillisecond_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextvars import copy_context
    from types import SimpleNamespace

    from roadmodel.providers._safety import hosted_timeout

    from app import budget

    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: 100.0))
    previous = hosted_timeout()
    with budget.attempt(107.0):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, hosted_timeout) for _ in range(2)]
            assert [future.result() for future in futures] == [7.0, 7.0]
    with pytest.raises(HTTPException):
        with budget.attempt(100.0001):
            pytest.fail("submillisecond attempt admitted")
    assert hosted_timeout() == previous


def test_diagnostics_do_not_keep_warning_or_numeric_instances() -> None:
    from app.redaction import _VISITOR_KEY, _scrub_record, install_redaction

    install_redaction()
    marker = secrets.token_hex(24)
    warning = UserWarning("ordinary")
    warning.private = marker  # type: ignore[attr-defined]

    class Number(int):
        pass

    number = Number(7)
    number.private = marker  # type: ignore[attr-defined]
    token = _VISITOR_KEY.set(marker)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn(warning, stacklevel=1)
            warnings.warn_explicit(warning, UserWarning, "fixture.py", 1)
        assert len(caught) == 2
        assert all(item.message is not warning for item in caught)
        assert all(not vars(item.message) for item in caught)
        record = logging.LogRecord("fixture", 30, "fixture.py", 1, "ordinary", (), None)
        record.numeric = number
        _scrub_record(record)
        assert type(record.__dict__["numeric"]) is int
        assert record.__dict__["numeric"] == 7
    finally:
        _VISITOR_KEY.reset(token)


@pytest.mark.parametrize("key", ["opaque-test-key", "s"])
def test_actual_uvicorn_access_formatter_contract(key: str) -> None:
    from uvicorn.logging import AccessFormatter

    from app.redaction import _VISITOR_KEY, _scrub_record

    token = _VISITOR_KEY.set(key)
    try:
        record = logging.LogRecord(
            "uvicorn.access",
            20,
            "fixture.py",
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("192.0.2.10:1234", "POST", "/v1/score?credential=" + key, "1.1", 200),
            None,
        )
        _scrub_record(record)
        _scrub_record(record)
        rendered = AccessFormatter(
            '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
        ).format(record)
        assert "200 OK" in rendered
        assert "192.0.2.10" not in rendered and "credential=" not in rendered
        assert "HTTP/1.1" in rendered
    finally:
        _VISITOR_KEY.reset(token)
