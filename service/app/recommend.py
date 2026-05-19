# service/app/recommend.py
from __future__ import annotations

from typing import Any

from roadmodel.config import load_config  # type: ignore[import-untyped]
from roadmodel.errors import (  # type: ignore[import-untyped]
    MissingProviderKeyError,
    ProviderCallError,
)
from roadmodel.recommend import recommend_structured  # type: ignore[import-untyped]

from .models import RecommendRequest, RecommendResponse

_PROVIDER_HINTS: dict[str, tuple[str, str]] = {
    "anthropic-haiku-4-5": ("anthropic", "claude-haiku-4-5-20251001"),
    "google-gemini-2.5-flash": ("google", "gemini-2.5-flash"),
}

_FALLBACK_CHAIN: tuple[str, ...] = (
    "anthropic-haiku-4-5",
    "google-gemini-2.5-flash",
)


def _config_for_hint(hint: str) -> Any:
    provider, model = _PROVIDER_HINTS[hint]
    return load_config(
        cli_provider=provider,
        cli_model=model,
        cli_user_context=None,
    )


def _provider_chain(context: dict[str, Any] | None) -> tuple[str, ...]:
    if not context:
        return _FALLBACK_CHAIN
    force = context.get("force_provider")
    if isinstance(force, str) and force in _PROVIDER_HINTS:
        rest = tuple(h for h in _FALLBACK_CHAIN if h != force)
        return (force, *rest)
    return _FALLBACK_CHAIN


def recommend(req: RecommendRequest) -> RecommendResponse:
    last_error: Exception | None = None

    for hint in _provider_chain(req.context):
        config = _config_for_hint(hint)
        try:
            result = recommend_structured(req.task_description, config)
            return RecommendResponse(
                model=result["model"],
                platform=result["platform"],
                settings=result["settings"],
                session_cost_estimate=result.get("session_cost_estimate"),
                comparison_table=result.get("comparison_table") or [],
            )
        except (MissingProviderKeyError, ProviderCallError) as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise ProviderCallError("No provider available for recommendation.")
