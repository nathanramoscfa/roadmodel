"""Exercise actual SDK transports and diagnostic channels without network calls."""

from __future__ import annotations

import inspect
import logging
import threading
import traceback
from typing import Any

import pytest

from roadmodel.errors import MalformedResponseError, ProviderCallError
from roadmodel.providers import anthropic as anthropic_adapter
from roadmodel.providers import google as google_adapter
from roadmodel.providers import openai as openai_adapter
from roadmodel.providers._safety import SDK_LOGGERS, private_transport, transport_timeout

MARKER = "SYNTHETIC_PRIVATE_DIAGNOSTIC"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_real_sdk_one_attempt_safe_error_and_logs(
    provider: str,
    failure: int | str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpx = pytest.importorskip("httpx")
    attempts: list[Any] = []
    clients: list[Any] = []

    def send(request: Any) -> Any:
        attempts.append(request.extensions["timeout"])
        if failure == "timeout":
            raise httpx.ReadTimeout(MARKER, request=request)
        return httpx.Response(
            failure,
            request=request,
            headers={"x-request-id": MARKER},
            json={"error": {"code": failure, "message": MARKER, "status": "UNAVAILABLE"}},
        )

    transport = httpx.Client(transport=httpx.MockTransport(send))
    if provider == "google":
        module = pytest.importorskip("google.genai")
        attribute, adapter = "Client", google_adapter
    elif provider == "anthropic":
        module = pytest.importorskip("anthropic")
        attribute, adapter = "Anthropic", anthropic_adapter
    else:
        module = pytest.importorskip("openai")
        attribute, adapter = "OpenAI", openai_adapter
    real = getattr(module, attribute)

    def construct(**kwargs: Any) -> Any:
        # Validate the adapter's exact constructor arguments against the real
        # installed callable before adding the local test transport.
        inspect.signature(real).bind(**kwargs)
        if provider == "google":
            kwargs["http_options"] = {**kwargs["http_options"], "httpx_client": transport}
        else:
            kwargs["http_client"] = transport
        client = real(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(module, attribute, construct)
    caplog.set_level(logging.DEBUG)
    try:
        with transport_timeout(120), pytest.raises(ProviderCallError) as caught:
            adapter.recommend(MARKER, MARKER, api_key="fixture-credential", max_output_tokens=8)
        error = caught.value
        assert len(attempts) == 1
        assert all(value == 120 for value in attempts[0].values())
        assert error.category == (
            "timeout" if failure == "timeout" else "quota" if failure == 429 else "upstream"
        )
        assert error.status_code == (None if failure == "timeout" else failure)
        assert error.__cause__ is None and error.__context__ is None
        assert MARKER not in "".join(traceback.format_exception(error))
        assert MARKER not in repr(error.__dict__)
        assert MARKER not in caplog.text
    finally:
        for client in clients:
            client.close()
        transport.close()


def test_transport_logging_is_context_local_and_restored(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    levels = {name: logging.getLogger(name).level for name in SDK_LOGGERS}
    entered, outside_logged = threading.Event(), threading.Event()

    @private_transport
    def scoped() -> None:
        for name in SDK_LOGGERS:
            for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
                logging.getLogger(name).log(level, "hidden-%s", name)
        logging.getLogger("roadmodel.test").info("unrelated application record")
        entered.set()
        assert outside_logged.wait(5)
        raise ValueError("synthetic failure")

    errors: list[Exception] = []

    def run() -> None:
        try:
            scoped()
        except ValueError as exc:
            errors.append(exc)
        logging.getLogger("httpx").info("restored after failure")

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(5)
    logging.getLogger("httpx").info("outside concurrent record")
    outside_logged.set()
    thread.join(5)
    assert not thread.is_alive() and errors
    assert "hidden-" not in caplog.text
    assert "outside concurrent record" in caplog.text
    assert "restored after failure" in caplog.text
    assert "unrelated application record" in caplog.text
    assert levels == {name: logging.getLogger(name).level for name in SDK_LOGGERS}


@pytest.mark.parametrize(
    "error", [ProviderCallError(MARKER), MalformedResponseError(MARKER), RuntimeError(MARKER)]
)
@pytest.mark.parametrize("debug", ["0", "1"])
def test_cli_never_renders_untrusted_errors(
    error: Exception,
    debug: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import click

    from roadmodel.cli import _error_mapped

    monkeypatch.setenv("ROADMODEL_DEBUG", debug)

    @_error_mapped
    def command() -> None:
        raise error

    with pytest.raises(click.exceptions.Exit):
        command()
    captured = capsys.readouterr()
    assert MARKER not in captured.out + captured.err


@pytest.mark.parametrize(
    ("provider", "message", "status", "category"),
    [
        ("Google", "API_KEY_INVALID " + MARKER, 400, "authentication"),
        ("Anthropic", "credit balance too low " + MARKER, 400, "quota"),
        ("OpenAI", MARKER, 401, "authentication"),
        ("OpenRouter", MARKER, 402, "quota"),
    ],
)
def test_safe_categories_preserve_visitor_classification(
    provider: str, message: str, status: int, category: str
) -> None:
    from roadmodel.providers._safety import safe_error

    class UpstreamError(Exception):
        status_code = status

    safe = safe_error(provider, UpstreamError(message))
    assert safe.category == category
    assert safe.status_code == status
    assert MARKER not in repr(safe) + repr(safe.__dict__)
