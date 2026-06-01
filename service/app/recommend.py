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

# Phase 4 Step 7 latency lever (issue #132). The warm-path latency
# gap is NOT the output token count — it is Gemini 2.5 Flash's
# default reasoning, which is decoded before (and counted against
# the budget of) the visible answer. A clean production baseline
# measured P50 ~13 s with the Gemini call ~99.7% of total. The
# 2026-05-31 incident proved that capping max_output_tokens alone
# cannot fix this: at 1024 the thinking tokens consumed the budget
# and the visible six-field block truncated below the parser
# threshold (MalformedResponseError on every call).
#
# roadmodel 0.2.3 adds an optional thinking_budget keyword to the
# Google provider (config.thinking_config.thinking_budget). We pass
# it ONLY on the Gemini path below. 0 disables Gemini's default
# reasoning entirely — the most aggressive latency cut — and is the
# starting value; a production A/B may tune it upward if response
# quality (the model pick) degrades. It is deliberately NOT passed
# on the Anthropic path: Anthropic extended-thinking has different
# semantics and the recommender response shape does not tolerate
# small caps on Anthropic (PR #128).
#
# The issue #133 fallback loop still catches MalformedResponseError,
# so any parser/selector drift on one provider degrades to the next
# instead of 500ing. See docs/phase04-latency-findings.md.
_GEMINI_THINKING_BUDGET = 0

# Phase 4 Step 7 latency tail (issue #146). thinking_budget=0 fixed the
# P50 (13.0s -> 1.6s) but left a bimodal P95 tail (~11s): a minority of
# requests where Gemini 2.5 Flash emits a runaway RATIONALE (the last,
# variable-length field of the response block) on complex planning
# prompts. A 2026-05-31 probe of the real recommender prompt at
# thinking_budget=0 measured normal visible output at 124-300 tokens with
# a single 4,125-token runaway on a planning prompt -- the exact tail.
#
# Because thinking is OFF, max_output_tokens is now a pure visible-response
# cap (no reasoning to consume it -- the 2026-05-31 cap=1024 incident only
# happened with thinking ON, see project_parser_selector_drift_incident).
# 768 sits ~2.5x above the observed normal max (300), so normal responses
# are never clipped, while runaway rationales are bounded -- cutting their
# decode time. Truncation is parser-safe: the 6 required fields (MODEL..
# CONVERSATION) are emitted first and RATIONALE is captured lazily to
# end-of-string, so even a forced cap=96 truncation still parses with the
# pick preserved. Gemini-only, like thinking_budget (never Anthropic, #128).
_GEMINI_MAX_OUTPUT_TOKENS = 768


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
        # Gemini-only: cap the default reasoning that dominates the
        # warm-path latency (#132), and bound the runaway-rationale P95
        # tail with a visible-output cap (#146). Anthropic is left
        # untouched on both (#128).
        is_gemini = config.provider == "google"
        thinking_budget = _GEMINI_THINKING_BUDGET if is_gemini else None
        max_output_tokens = _GEMINI_MAX_OUTPUT_TOKENS if is_gemini else None
        try:
            result = recommend_structured(
                req.task_description,
                config,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
            )
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
