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
  ``visitor_key_rejected``; its rate limit, quota or exhausted credits (429,
  402) -> ``visitor_quota``;
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
from collections.abc import Callable, Coroutine
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
from .budget import attempt, deadline
from .engines import EVALUATED, REGISTRY, VISITOR_PROVIDERS, EngineSpec
from .models import LadderResponse, RecommendRequest
from .recommend import _BUNDLED_USER_CONTEXT, ladder_once
from .redaction import _VISITOR_KEY as _VISITOR_KEY
from .redaction import REDACTED as REDACTED
from .redaction import VisitorKeyFilter as VisitorKeyFilter
from .redaction import install_redaction as install_redaction
from .redaction import scrub as scrub

logger = logging.getLogger(__name__)

KEY_HEADER: Final = "X-Roadmodel-Visitor-Key"
PROVIDER_HEADER: Final = "X-Roadmodel-Visitor-Provider"


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
# (OpenRouter answers it with 402 Payment Required, a quota whatever its text.)
_QUOTA_TEXT: Final = re.compile(r"credit balance|insufficient_quota|quota", re.IGNORECASE)


def classify(exc: BaseException) -> tuple[int, str]:
    """(status, code) for a failed visitor call."""
    if isinstance(exc, ProviderCallError):
        # New packages retain only safe categories, including provider-specific
        # 400 responses. Keep the legacy status/cause path during rollout.
        if getattr(exc, "category", None) == "authentication":
            return 401, "visitor_key_rejected"
        if getattr(exc, "category", None) == "quota":
            return 429, "visitor_quota"
        status = _upstream_status(exc)
        text = str(exc.__cause__ or exc)
        if status in (401, 403) or (status == 400 and _REJECTED_TEXT.search(text)):
            return 401, "visitor_key_rejected"
        if status in (402, 429) or (status == 400 and _QUOTA_TEXT.search(text)):
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

    expires = deadline()
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
            with attempt(expires):
                result = ladder_once(req, spec.hint, config, votes=False)
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
