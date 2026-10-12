"""Private provider transport policy without importing optional SDKs."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, TypeVar, cast

from roadmodel.errors import ProviderCallError

_ACTIVE: ContextVar[bool] = ContextVar("roadmodel_provider_call", default=False)
_TIMEOUT: ContextVar[float] = ContextVar("roadmodel_provider_timeout", default=600.0)
SDK_LOGGERS = (
    "openai._base_client",
    "openai._response",
    "openai._legacy_response",
    "openai.resources.responses.responses",
    "anthropic._base_client",
    "anthropic._response",
    "anthropic._legacy_response",
    "google_genai._api_client",
    "google_genai._common",
    "google_genai._transformers",
    "google_genai.models",
    "google_genai.types",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)


class _PrivateTransport(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK diagnostics can contain complete prompts, headers and raw errors.
        # No credential is stored here; unrelated calls keep their normal logs.
        return not _ACTIVE.get()


_FILTER = _PrivateTransport()
F = TypeVar("F", bound=Callable[..., Any])


def private_transport(function: F) -> F:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        for name in SDK_LOGGERS:
            logging.getLogger(name).addFilter(_FILTER)
        token = _ACTIVE.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)

    return cast(F, wrapped)


@contextmanager
def transport_timeout(seconds: float) -> Iterator[None]:
    """Override hosted per-phase network timeouts for this call context."""
    if not 0 < seconds <= 600:
        raise ValueError("Invalid provider timeout.")
    token = _TIMEOUT.set(seconds)
    try:
        yield
    finally:
        _TIMEOUT.reset(token)


def hosted_timeout() -> float:
    return _TIMEOUT.get()


def safe_error(provider: str, error: Exception) -> ProviderCallError:
    """Retain only closed categories and an HTTP status, never the SDK object."""
    status = None
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value < 600:
            status = value
            break
    category = "upstream"
    if status in (401, 403):
        category = "authentication"
    elif status in (402, 429):
        category = "quota"
    elif status == 400:
        # These providers use 400 for key/credit failures. Inspect privately;
        # only the selected category survives this function.
        text = str(error).lower()
        if provider == "Google" and ("api_key_invalid" in text or "api key not valid" in text):
            category = "authentication"
        elif provider == "Anthropic" and any(
            value in text for value in ("credit balance", "insufficient_quota", "quota")
        ):
            category = "quota"
    elif type(error).__name__ in {
        "APITimeoutError",
        "TimeoutException",
        "ReadTimeout",
        "ConnectTimeout",
        "WriteTimeout",
        "PoolTimeout",
    }:
        category = "timeout"
    elif type(error).__name__ in {"APIConnectionError", "ConnectError"}:
        category = "connection"
    return ProviderCallError(
        f"{provider} request failed ({category}).", status_code=status, category=category
    )
