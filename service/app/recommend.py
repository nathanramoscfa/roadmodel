# service/app/recommend.py
from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from roadmodel.config import load_config  # type: ignore[import-untyped]
from roadmodel.errors import (  # type: ignore[import-untyped]
    MissingProviderKeyError,
    ProviderCallError,
)
from roadmodel.recommend import recommend_structured  # type: ignore[import-untyped]

from .models import RecommendRequest, RecommendResponse


def _bootstrap_user_context() -> Path:
    """Materialize the bundled user-context template to /tmp on cold start.

    Anonymous web-tier requests don't carry per-user context, and the roadmodel
    recommender's default path (~/.config/roadmodel/user-context.md) doesn't
    exist on Vercel's read-only Function filesystem. Write the template that
    ships with the roadmodel package to /tmp (the one writable location on
    Fluid Compute) and return its path. Idempotent across warm invocations.
    """
    target = Path("/tmp/roadmodel-user-context.md")  # noqa: S108
    if not target.exists():
        template = resources.files("roadmodel.data") / "user-context.example.md"
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


_BUNDLED_USER_CONTEXT = _bootstrap_user_context()

_PROVIDER_HINTS: dict[str, tuple[str, str]] = {
    "anthropic-haiku-4-5": ("anthropic", "claude-haiku-4-5-20251001"),
    "google-gemini-2.5-flash": ("google", "gemini-2.5-flash"),
}

_FALLBACK_CHAIN: tuple[str, ...] = (
    "anthropic-haiku-4-5",
    "google-gemini-2.5-flash",
)

# Phase 4 Step 7b — per-provider output caps. The token cap that
# unblocks the warm-path latency budget is Gemini-specific: Gemini
# 2.5 Flash defaults to 8192 max output tokens and the baseline
# showed P50 service_provider_ms = 17,014 ms. The recommender's
# six-field block + rationale fits well under 1024 Gemini tokens
# in practice, so capping there drops decode-time ~8x without
# truncating output.
#
# DO NOT extend this cap to Anthropic Haiku (the fallback). 1024
# is too low for Anthropic's tokenizer / response shape; the
# response gets truncated before all six fields are emitted and
# the parser raises MalformedResponseError. Hotfix for the
# 2026-05-31 production incident discovered during the post-fix
# sweep. Per-provider rather than per-call so the fallback chain
# can keep its full output budget while Gemini caps tightly. See
# docs/phase04-latency-findings.md for the rubric trigger.
_PROVIDER_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "google-gemini-2.5-flash": 1024,
}


def _config_for_hint(hint: str) -> Any:
    provider, model = _PROVIDER_HINTS[hint]
    return load_config(
        cli_provider=provider,
        cli_model=model,
        cli_user_context=_BUNDLED_USER_CONTEXT,
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
            result = recommend_structured(
                req.task_description,
                config,
                max_output_tokens=_PROVIDER_MAX_OUTPUT_TOKENS.get(hint),
            )
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
