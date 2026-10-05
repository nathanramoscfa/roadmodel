# service/app/visitor.py
"""The visitor lane: one recommendation paid for with the visitor's own key.

``POST /v1/visitor/recommend/ladder`` runs exactly one ladder call on the key
the web edge forwards in ``X-Roadmodel-Visitor-Key``, for the provider named in
``X-Roadmodel-Visitor-Provider``. The key is used for that call and dropped
with the request. Its contract:

- One call, on the visitor's key, on an engine of the visitor's provider: the
  requested engine when it passed the engine eval, else the registry's
  ``visitor_defaults`` engine. The Config is built here from the key, never by
  ``load_config``, so no environment key can stand in for it, and there is no
  fallback chain, no retry on another provider and no fan-out. A failing
  visitor key therefore never reaches an operator key.
- Failures map to a code: the provider refused the key (401/403) ->
  ``visitor_key_rejected``; its rate limit or quota (429) -> ``visitor_quota``;
  anything else -> ``provider_error``. The body carries the code and provider
  only, never SDK text, which can echo part of the key.
- While the request runs, a ContextVar holds the key and a redaction filter
  replaces it (and anything shaped like a provider key) in every log record,
  so no log line, warning or traceback carries it.
"""

from __future__ import annotations

import logging
import re
import time
import traceback
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from typing import Any, Final

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from roadmodel.config import Config  # type: ignore[import-untyped]
from roadmodel.errors import (  # type: ignore[import-untyped]
    MalformedResponseError,
    ProviderCallError,
)

from .auth import require_bearer
from .engines import EVALUATED, REGISTRY, VISITOR_PROVIDERS, EngineSpec
from .models import LadderResponse, RecommendRequest
from .recommend import _BUNDLED_USER_CONTEXT, ladder_once

logger = logging.getLogger(__name__)

KEY_HEADER: Final = "X-Roadmodel-Visitor-Key"
PROVIDER_HEADER: Final = "X-Roadmodel-Visitor-Provider"
REDACTED: Final = "[visitor-key]"

# The visitor key of the request being served, for the redaction filter.
_VISITOR_KEY: ContextVar[str | None] = ContextVar("roadmodel_visitor_key", default=None)

# Anything shaped like a provider key, whoever's it is: Anthropic (sk-ant-),
# OpenAI and other sk- keys, Google (AIza). Scrubbed even with no visitor key
# in play, so an operator key echoed by an SDK is caught the same way.
_KEY_SHAPES: Final = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}"
)


def scrub(text: str) -> str:
    """``text`` with the current visitor key and every key-shaped token
    replaced by ``[visitor-key]``."""
    key = _VISITOR_KEY.get()
    if key:
        text = text.replace(key, REDACTED)
    return _KEY_SHAPES.sub(REDACTED, text)


def _scrub_arg(value: object) -> object:
    # Numbers keep their type so %d / %f still format; anything else is
    # rendered and scrubbed, since an exception or object can print the key.
    if value is None or isinstance(value, bool | int | float):
        return value
    return scrub(str(value))


def _scrub_record(record: logging.LogRecord) -> None:
    if getattr(record, "_visitor_scrubbed", False):
        return
    record.msg = scrub(str(record.msg))
    if isinstance(record.args, dict):
        record.args = {k: _scrub_arg(v) for k, v in record.args.items()}
    elif record.args:
        record.args = tuple(_scrub_arg(a) for a in record.args)
    if record.exc_info:
        # Render the traceback now, scrubbed, and drop the live exception: a
        # handler would otherwise format it later from the unscrubbed object.
        text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
        record.exc_text = scrub(text)
        record.exc_info = None
    elif record.exc_text:
        record.exc_text = scrub(record.exc_text)
    record._visitor_scrubbed = True


class VisitorKeyFilter(logging.Filter):
    """Replaces the visitor key, and any key-shaped token, in a log record's
    message, arguments and traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        _scrub_record(record)
        return True


_FILTER: Final = VisitorKeyFilter()


def install_redaction() -> None:
    """Install the filter on the root logger and its handlers, and scrub every
    record as it is created.

    A logger's filters see only records logged on that logger, not those that
    propagate up from child loggers (uvicorn's, an SDK's, this module's), so
    the filter on the root logger alone would miss most of them. The record
    factory scrubs each record at creation, whatever logger and handler it
    goes through. Idempotent."""
    root = logging.getLogger()
    if _FILTER not in root.filters:
        root.addFilter(_FILTER)
    for handler in root.handlers:
        if _FILTER not in handler.filters:
            handler.addFilter(_FILTER)
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_visitor_redaction", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _scrub_record(record)
        return record

    factory._visitor_redaction = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


install_redaction()


def _error(status: int, code: str, provider: str | None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "provider": provider})


class _VisitorRoute(APIRoute):
    """The router's exception handler. FastAPI registers exception handlers on
    the app, not on a router, so this route class wraps the handler instead:
    anything the endpoint did not map itself (an exception from a guard, the
    cost estimate, the response model) becomes a 502 provider_error, logged at
    WARNING by type alone. HTTPException (the bearer check) and request
    validation keep their own handling."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except (HTTPException, RequestValidationError):
                raise
            except Exception as exc:  # noqa: BLE001 - the router's catch-all, by design
                provider = request.headers.get(PROVIDER_HEADER)
                logger.warning(
                    "visitor ladder failed unexpectedly: provider=%s error=%s",
                    provider if provider in VISITOR_PROVIDERS else None,
                    type(exc).__name__,
                )
                return _error(
                    502, "provider_error", provider if provider in VISITOR_PROVIDERS else None
                )

        return guarded


router = APIRouter(route_class=_VisitorRoute)


def resolve_engine(provider: str, context: dict[str, Any] | None) -> EngineSpec:
    """The engine a visitor's key runs: the one they asked for when it is an
    engine of their key's provider that passed the engine eval (any menu tier:
    the visitor pays), else that provider's ``visitor_defaults`` engine."""
    requested = (context or {}).get("force_provider")
    if isinstance(requested, str):
        spec = REGISTRY.engines.get(requested)
        if spec is not None and spec.provider == provider and requested in EVALUATED:
            return spec
    return REGISTRY.engines[REGISTRY.visitor_defaults[provider]]


def _upstream_status(exc: BaseException) -> int | None:
    """The HTTP status the provider answered with, read off the SDK error the
    adapter wrapped (``raise ProviderCallError(...) from exc``): ``status_code``
    on the OpenAI and Anthropic SDKs, ``code`` on Google's."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("status_code", "code"):
            value = getattr(current, attr, None)
            if isinstance(value, int) and not isinstance(value, bool) and 100 <= value < 600:
                return value
        current = current.__cause__ or current.__context__
    return None


# Provider answers that refuse the key without a 401/403: Google answers an
# invalid key with 400 INVALID_ARGUMENT, reason API_KEY_INVALID.
_REJECTED_TEXT: Final = re.compile(r"API_KEY_INVALID|API key not valid", re.IGNORECASE)
# Anthropic answers an exhausted prepaid balance with 400 "credit balance is too low".
_QUOTA_TEXT: Final = re.compile(r"credit balance|insufficient_quota|quota", re.IGNORECASE)


def classify(exc: BaseException) -> tuple[int, str]:
    """(status, code) for a failed visitor call."""
    if isinstance(exc, ProviderCallError):
        status = _upstream_status(exc)
        text = str(exc.__cause__ or exc)
        if status in (401, 403) or (status == 400 and _REJECTED_TEXT.search(text)):
            return 401, "visitor_key_rejected"
        if status == 429 or (status in (400, 402) and _QUOTA_TEXT.search(text)):
            return 429, "visitor_quota"
    return 502, "provider_error"


@router.post(
    "/v1/visitor/recommend/ladder",
    response_model=LadderResponse,
    dependencies=[Depends(require_bearer)],
)
def visitor_ladder_endpoint(
    req: RecommendRequest, request: Request, response: Response
) -> LadderResponse | JSONResponse:
    provider = (request.headers.get(PROVIDER_HEADER) or "").strip().lower()
    key = (request.headers.get(KEY_HEADER) or "").strip()
    # Both checked before any call, so a bad request costs nothing upstream.
    if provider not in VISITOR_PROVIDERS:
        return _error(400, "visitor_provider_unsupported", None)
    if not key:
        return _error(400, "visitor_key_missing", provider)

    token = _VISITOR_KEY.set(key)
    overall_start = time.perf_counter()
    provider_ms = 0
    try:
        spec = resolve_engine(provider, req.context)
        config = Config(
            provider=spec.provider,
            model=spec.model,
            api_key=key,
            user_context_path=_BUNDLED_USER_CONTEXT,
        )
        provider_start = time.perf_counter()
        try:
            result = ladder_once(req, spec.hint, config)
        except (ProviderCallError, MalformedResponseError) as exc:
            status, code = classify(exc)
            logger.warning(
                "visitor ladder failed: provider=%s engine=%s outcome=%s error=%s",
                provider,
                spec.hint,
                code,
                type(exc).__name__,
            )
            return _error(status, code, provider)
        provider_ms = int((time.perf_counter() - provider_start) * 1000)
        return result
    finally:
        total_ms = int((time.perf_counter() - overall_start) * 1000)
        response.headers["X-Roadmodel-Timing"] = (
            f"service_scoring_ms={max(0, total_ms - provider_ms)};service_provider_ms={provider_ms}"
        )
        _VISITOR_KEY.reset(token)
