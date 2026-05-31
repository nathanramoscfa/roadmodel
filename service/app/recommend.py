# service/app/recommend.py
from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import Any

from roadmodel.config import load_config  # type: ignore[import-untyped]
from roadmodel.errors import (  # type: ignore[import-untyped]
    MalformedResponseError,
    MissingProviderKeyError,
    ProviderCallError,
)
from roadmodel.recommend import recommend_structured  # type: ignore[import-untyped]

from .models import RecommendRequest, RecommendResponse

logger = logging.getLogger(__name__)


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

# Phase 4 Step 7b cap REMOVED 2026-05-31 to recover from a
# production incident. The premise that the recommender's response
# "fits well under 1024 tokens" turned out to be false: Gemini 2.5
# Flash at max_output_tokens=1024 emits a response that fails the
# six-field regex parser in roadmodel.recommend.parse_response,
# raising MalformedResponseError.
#
# As of issue #133 the fallback loop below catches
# MalformedResponseError too, so a parser/selector drift on one
# provider degrades to the next provider in the chain instead of
# leaking an uncaught 500. If EVERY provider drifts, the terminal
# `raise last_error` re-raises it — an unhandled 500, the same
# terminal behavior as the pre-existing all-providers-ProviderCallError
# path; the drift guard in tests/test_selector_parser_drift_guard.py
# (issue #134) is what stops whole-chain schema/parser drift from
# shipping in the first place.
#
# What remains before a cap can be re-introduced is finding a
# max_output_tokens value Gemini's response shape actually fits
# within (issue #132). Until then the service runs without a cap
# (Gemini SDK default 8192) — matches pre-Step-7b behavior. The
# warm-path latency budget stays missed (P50 ~17 s); that is a known
# regression tracked by issue #132, a much smaller blast radius than
# 500s on every call. See docs/phase04-latency-findings.md.


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
            result = recommend_structured(req.task_description, config)
            return RecommendResponse(
                model=result["model"],
                platform=result["platform"],
                settings=result["settings"],
                session_cost_estimate=result.get("session_cost_estimate"),
                comparison_table=result.get("comparison_table") or [],
            )
        except (MissingProviderKeyError, ProviderCallError, MalformedResponseError) as exc:
            last_error = exc
            if isinstance(exc, MalformedResponseError):
                # Parser/selector drift (the 2026-05-31 incident class): the
                # provider returned text the bundled parser could not read.
                # Log it so the drift is visible in the function logs, then
                # fall through to the next provider instead of 500ing. The raw
                # response is intentionally NOT logged (it can echo user input);
                # issue #132 adds bounded debug capture inside parse_response.
                logger.warning(
                    "provider hint %r returned an unparseable response; "
                    "falling through to the next provider in the chain",
                    hint,
                )
            continue

    if last_error is not None:
        raise last_error
    raise ProviderCallError("No provider available for recommendation.")
