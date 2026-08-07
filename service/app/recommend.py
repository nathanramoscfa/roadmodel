# service/app/recommend.py
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any

from roadmodel import cost  # type: ignore[import-untyped]
from roadmodel.config import load_config  # type: ignore[import-untyped]
from roadmodel.errors import (  # type: ignore[import-untyped]
    MalformedResponseError,
    MissingProviderKeyError,
    ProviderCallError,
)
from roadmodel.recommend import (  # type: ignore[import-untyped]
    _structured_settings,
    recommend_structured,
    recommend_structured_ladder,
)

from .funding import (
    AccessGuard,
    FundingGuard,
    access_guard_from_request,
    canonical_model_name,
    funding_guard_from_request,
    platform_dials,
    resolve_allowed_jurisdictions,
    user_context_from_request,
)
from .models import BackupPick, LadderResponse, RecommendRequest, RecommendResponse

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

# Point roadmodel.cost's funding resolution at the bundled user-context so
# session_cost_estimate / comparison_table reflect the funded-platform
# discounts (#164). cost.estimate_session_cost reads ROADMODEL_USER_CONTEXT
# (or a default path that doesn't exist on the read-only Function fs), NOT a
# per-request arg — per-user personalization is the (package-gated) #163.
# setdefault so an explicit deployment override still wins.
os.environ.setdefault("ROADMODEL_USER_CONTEXT", str(_BUNDLED_USER_CONTEXT))

# Representative session size for the cost projection (#164). The cost panel
# shows what a typical session with the recommended model would cost (and how
# alternatives rank by what the user's subscriptions fund), so we project from
# the task_description length with a sane floor + a typical answer size rather
# than the recommend call's own tokens. Heuristic, intentionally simple.
_COST_OUTPUT_TOKENS = 2000
_COST_INPUT_FLOOR = 1000


def _estimate_session_tokens(task_description: str) -> tuple[int, int]:
    input_tokens = max(_COST_INPUT_FLOOR, len(task_description) // 4)
    return input_tokens, _COST_OUTPUT_TOKENS


def _session_cost(
    model: str, platform: str, task_description: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Best-effort cost projection. NEVER raises into the request path: a
    cost-catalog resolution miss must not turn a good recommendation into a
    500 (the recommendation itself already succeeded)."""
    try:
        input_tokens, output_tokens = _estimate_session_tokens(task_description)
        primary = cost.estimate_session_cost(
            model, platform, input_tokens=input_tokens, output_tokens=output_tokens
        )
        ranked = cost.compare_alternatives_funding_rank(
            model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        return asdict(primary), [asdict(est) for est in ranked]
    except Exception:  # noqa: BLE001 - cost is best-effort, never fatal
        logger.warning("session cost estimate failed (non-fatal)", exc_info=True)
        return None, []


_PROVIDER_HINTS: dict[str, tuple[str, str]] = {
    "anthropic-haiku-4-5": ("anthropic", "claude-haiku-4-5-20251001"),
    "google-gemini-2.5-flash": ("google", "gemini-2.5-flash"),
    # Phase 4.5 T3b signed-in quality tier: Gemini 2.5 Pro with thinking ON
    # (params below). The free/anon tier stays on 2.5 Flash; the web edge only
    # routes signed-in users here when RECOMMENDER_FRONTIER_ENABLED is on.
    "google-gemini-2.5-pro": ("google", "gemini-2.5-pro"),
    # GPT-5 mini — the eval-backed recommender engine (best instruction-adherence
    # + ~3x cheaper with OpenAI automatic prefix caching). Reachable via
    # force_provider "openai-gpt-5-mini" (set by the web ENGINE_OVERRIDES canary);
    # runs at minimal reasoning (params below).
    "openai-gpt-5-mini": ("openai", "gpt-5-mini"),
}

# The frontier model id — keyed on directly so its thinking-ON params apply
# without a separate request flag (the model IS the tier signal).
_GEMINI_FRONTIER_MODEL = "gemini-2.5-pro"

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
# 512 sits ~1.7x above the observed normal max (300), so normal responses
# are never clipped, while runaway rationales are bounded -- cutting their
# decode time. Truncation is parser-safe: the 6 required fields (MODEL..
# CONVERSATION) are emitted first and RATIONALE is captured lazily to
# end-of-string, so even a forced cap=96 truncation still parses with the
# pick preserved. Gemini-only, like thinking_budget (never Anthropic, #128).
#
# Value history: an initial 768 cap (2026-06-01 prod sweep) cut P95 from
# 11,084ms to 5,530ms -- the runaway tail collapsed, but P95 still missed
# the <=5,000ms budget by ~530ms because the cap-bound long generations
# landed at ~5.5-6.3s. The capped tail scales with the token count (~187
# tok/s decode + ~1.4s base), so 512 brings it to ~4.1s with margin. 512
# is still well above the normal-output ceiling, so the tightening only
# trims over-long (>1.7x normal) rationales, never the pick.
_GEMINI_MAX_OUTPUT_TOKENS = 512

# Recommender determinism (#176). Without an explicit temperature Gemini
# samples at its default (~1.0), so the SAME task_description returns
# different model picks run-to-run (a prod dogfooding sweep saw ~25% of
# identical requests flip to a different model). 0.0 = greedy/deterministic,
# the right default for a recommender (consistency builds trust); tunable up
# if pick diversity is ever wanted. Gemini-only, like the two caps above
# (never Anthropic, #128).
_GEMINI_TEMPERATURE = 0.0

# Phase 4.5 T3b — signed-in QUALITY-tier Gemini params (frontier model only).
# The free tier runs Gemini 2.5 Flash with reasoning OFF for latency (#132); the
# quality tier runs Gemini 2.5 Pro with reasoning ON, which is what closes the
# adherence residuals (#185 cost-demotion, #188 thinking-prose) the free engine
# left open. The bake-off (2026-06-06) showed thinking_budget=512 is the sweet
# spot: thinking_budget=None starved the visible block (no-output failures) and
# thinking_budget=1024 doubled latency (~12s) for no quality gain, while 512
# cleared the residuals at ~6-7s (within the quality-tier P50<=8s budget). The
# combined max_output_tokens must leave room for both the bounded thinking and
# the visible six-field block, hence 2048 (vs the free tier's 512).
_GEMINI_FRONTIER_THINKING_BUDGET = 512
_GEMINI_FRONTIER_MAX_OUTPUT_TOKENS = 2048

# GPT-5* reasoning-model engine params. The OpenAI provider maps thinking_budget
# -> reasoning.effort (0 -> minimal); minimal keeps the structured-classification
# recommender task fast (~7s vs ~33s at low effort) and cheap. The output cap is
# generous because reasoning tokens ALSO count against max_output_tokens on these
# models — too tight and the reasoning empties the budget, returning no text.
_GPT5_THINKING_BUDGET = 0
_GPT5_MAX_OUTPUT_TOKENS = 2048

# Ladder mode (tasks #1/#3) emits THREE six/seven-field blocks in one response,
# so the visible-output cap must scale ~3x the single-block cap or the third
# (COST) block truncates below the parser threshold — the same failure class as
# the 2026-05-31 incident, but from too-tight a cap on a 3x-longer body.
_LADDER_OUTPUT_MULTIPLIER = 3


def _ladder_output_cap(single_block_cap: int) -> int:
    """Scale a single-block output cap for the three-block ladder response."""
    return single_block_cap * _LADDER_OUTPUT_MULTIPLIER


# Output contract v2 — the structured `settings` a pick carries must match the
# PLATFORM-CONDITIONAL emission rule: EFFORT / THINKING exist only where the
# access method's `exposes_thinking` is `yes`, MAX MODE only where
# `exposes_max_mode` is `yes`, and a dial the surface LACKS is ABSENT — never
# `Off`, never `N/A` ("this control exists and is off" is a different claim from
# "this surface has no such control", and the UI renders the difference).
#
# This normalization stays in the SERVICE because the settings dict reaching it
# is whatever the DEPLOYED roadmodel emits: the package ships to prod only via a
# PyPI release + floor bump, so during migration the service sees BOTH shapes —
# v1 (`thinking` carrying an effort word, `max_mode` present on every surface)
# and v2 (`effort` + a two-position `thinking`). It DUAL-ACCEPTS both and emits
# the v2 shape either way. It also supersedes the old #188 hard-coded
# `_NO_THINKING_PLATFORMS` set, whose Cursor entry force-reverted the package's
# deliberate Cursor value (fixed in #387, silently re-introduced by #389) — the
# catalog's own attributes are the single source now.

# `thinking` values that read as "no reasoning" on either contract version — v1
# also spelled "no dial" as `N/A` here, which v2 replaces with an absent line.
_OFFISH_THINKING = frozenset({"off", "no", "none", "n/a", "na", "-", ""})

# The two-position TOGGLE values v2's THINKING field may carry. Anything outside
# these ∪ _OFFISH_THINKING is a reasoning LEVEL wearing the v1 field name.
_TOGGLE_ON_VALUES = frozenset({"on", "yes", "true", "enabled"})

# Settings keys that carry a reasoning LEVEL rather than a toggle.
_LEVEL_SETTING_KEYS = ("effort", "intelligence")


def _is_level_value(value: str) -> bool:
    """Whether a `thinking` value is an effort LEVEL rather than an On/Off toggle."""
    lowered = value.strip().lower()
    return lowered not in _OFFISH_THINKING and lowered not in _TOGGLE_ON_VALUES


def _normalize_settings_contract(platform: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Coerce a pick's structured settings into the v2 platform-conditional shape.

    Each rule fires only when the catalog actually describes that dial (an
    unknown platform / attribute is left untouched — fail-open, never invent a
    shape for a surface we can't describe):

    - Surface with NO reasoning dial: drop `effort` / `intelligence`, and drop a
      `thinking` value that is a reasoning LEVEL. A level is meaningless where no
      dial exists (#188: Gemini filled one on 6 of 7 Cursor probes) and v2 says
      such a line is ABSENT, never `N/A`. An On/Off value is deliberately KEPT —
      that is the package's display reframe for Cursor ("reasoning happens, it
      just isn't user-dialable"), and the package OWNS it: a service override
      that force-reverted it was the #387 bug, silently re-introduced by #389.
    - Surface with NO Max Mode dial: drop `max_mode` (v1 pinned it "Off"
      everywhere, so an Anthropic-API pick showed a dial it does not have).
    - Thinking-capable surface carrying the v1 shape (`thinking` holding the
      LEVEL, no `effort`/`intelligence` key): split it into `effort` (the level)
      + `thinking` (the On/Off toggle). "THINKING: Max" is the bug v2 split.
    """
    dials = platform_dials(platform)
    out = dict(settings)
    thinking = out.get("thinking")

    if dials.get("thinking") is False:
        for key in _LEVEL_SETTING_KEYS:
            out.pop(key, None)
        if not isinstance(thinking, str) or _is_level_value(thinking):
            out.pop("thinking", None)
    elif dials.get("thinking") is True and isinstance(thinking, str):
        value = thinking.strip()
        if value.lower() in _OFFISH_THINKING:
            # On a surface that HAS the dial, the honest two-position reading of
            # any off-ish value (including v1's `N/A`) is Off.
            out["thinking"] = "Off"
        elif _is_level_value(value) and not any(k in out for k in _LEVEL_SETTING_KEYS):
            out["effort"] = value
            out["thinking"] = "On"

    if dials.get("max_mode") is False:
        out.pop("max_mode", None)
    return out


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


def _unavailable_models_from_request(context: dict[str, Any] | None) -> list[str] | None:
    """Pull the runtime unavailable-model id list the web edge forwards in context.

    The web /api/recommend route reads the `model_availability` table and forwards
    the unavailable ids here; we hand them to recommend_structured as a runtime
    Step-0a override (roadmodel >=0.2.9). Defensive: only non-empty strings are
    honored; anything else -> None (no override, the bundled <availability-context>
    defaults still apply). Fail-open by design — a missing/garbled list never
    blocks a recommendation, it just falls back to the static defaults.
    """
    if not context:
        return None
    raw = context.get("unavailable_models")
    if not isinstance(raw, list):
        return None
    ids = [s.strip() for s in raw if isinstance(s, str) and s.strip()]
    return ids or None


def _budget_priority_of(context: dict[str, Any] | None) -> str:
    """The request's budget-priority id (cheap/balanced/best), defaulting to
    balanced. Drives the AccessGuard's tier-appropriate substitute ranking on
    the single-pick path (the ladder maps its tier labels instead)."""
    raw = (context or {}).get("budget_priority")
    return raw if isinstance(raw, str) and raw else "balanced"


def _availability_authoritative_from_request(context: dict[str, Any] | None) -> bool:
    """Whether the web edge read the availability table SUCCESSFULLY this request.

    True -> the forwarded ``unavailable_models`` list is the COMPLETE current
    unavailable set; the selector treats it as authoritative and supersedes the
    bundled ``<availability-context>`` fallback (so a model the probe/AI verifier
    has RESTORED is recommendable again WITHOUT a package release). Absent or not
    exactly True -> False: additive/fallback mode, so a legacy/direct caller or a
    failed (fail-open) edge read still gets the conservative static defaults.
    """
    if not context:
        return False
    return context.get("availability_authoritative") is True


def recommend(req: RecommendRequest) -> RecommendResponse:
    last_error: Exception | None = None

    # Build the per-user funding context once (provider-independent): the user's
    # held subscriptions + enabled API providers, so model SELECTION can prefer a
    # surface the user funds at $0 (Phase 4.8 T2b, #163). None when the request
    # declares no funding (anon/free) -> recommend_structured falls back to the
    # bundled template, leaving that path unchanged.
    user_context_text = user_context_from_request(req.context)
    # Funded-platform honesty guard (#444) — built from the SAME declared
    # funding the user-context above renders, active on exactly the same
    # requests (None on the anon / bundled-template path).
    funding_guard = funding_guard_from_request(req.context)
    # Access-restriction guard (#445) — enforces the accessible-model allowlist
    # deterministically; None (no restriction) on the anon / no-funding path. It
    # also carries the operator's platform allow/deny list (Step A00), read from
    # the SAME req.context: unlike allowed_jurisdictions there is no package
    # kwarg to forward it through, so it reaches the engine as prompt bias (the
    # user-context "Allowed / excluded platforms" section) and is ENFORCED here.
    access_guard = access_guard_from_request(req.context)
    budget_priority = _budget_priority_of(req.context)
    # Runtime availability override (Phase 4.9 B2): the web edge forwards the
    # model_availability unavailable-ids so a benched model is excluded without a
    # roadmodel release. Provider-independent, so resolve once. None for legacy /
    # direct callers -> only the bundled <availability-context> defaults apply.
    unavailable_models = _unavailable_models_from_request(req.context)
    # When the edge read the availability table successfully, its list is the
    # complete truth and supersedes the bundled fallback (lets a RESTORED model be
    # recommended without a release). A failed/absent read -> False -> fail-closed
    # static defaults still apply.
    availability_authoritative = _availability_authoritative_from_request(req.context)
    # The user's permitted jurisdictions (or the baseline) — forwarded to the
    # package so the cross-provider backup substitution only picks a region-valid
    # fallback (0.2.20).
    allowed_jurisdictions = resolve_allowed_jurisdictions(req.context)

    for hint in _provider_chain(req.context):
        config = _config_for_hint(hint)
        # Gemini-only: cap the default reasoning that dominates the
        # warm-path latency (#132), and bound the runaway-rationale P95
        # tail with a visible-output cap (#146). Anthropic is left
        # untouched on both (#128).
        is_gemini = config.provider == "google"
        is_frontier = is_gemini and config.model == _GEMINI_FRONTIER_MODEL
        is_openai_gpt5 = config.provider == "openai" and (config.model or "").startswith("gpt-5")
        if is_frontier:
            # Quality tier: reasoning ON, larger combined cap (T3b).
            thinking_budget: int | None = _GEMINI_FRONTIER_THINKING_BUDGET
            max_output_tokens: int | None = _GEMINI_FRONTIER_MAX_OUTPUT_TOKENS
        elif is_gemini:
            # Free tier: reasoning OFF (#132), tight visible cap (#146).
            thinking_budget = _GEMINI_THINKING_BUDGET
            max_output_tokens = _GEMINI_MAX_OUTPUT_TOKENS
        elif is_openai_gpt5:
            # GPT-5 engine: minimal reasoning (fast/cheap), generous output cap.
            thinking_budget = _GPT5_THINKING_BUDGET
            max_output_tokens = _GPT5_MAX_OUTPUT_TOKENS
        else:
            thinking_budget = None
            max_output_tokens = None
        temperature = _GEMINI_TEMPERATURE if is_gemini else None
        try:
            result = recommend_structured(
                req.task_description,
                config,
                user_context_text=user_context_text,
                unavailable_models=unavailable_models,
                availability_authoritative=availability_authoritative,
                allowed_jurisdictions=allowed_jurisdictions,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
                temperature=temperature,
            )
            return _pick_response(
                result, req.task_description, funding_guard, access_guard, budget_priority
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


# Ladder tier label -> the budget-priority id the AccessGuard ranks substitutes
# by (quality/balanced/cost order). The single-pick path passes the request's
# budget_priority directly.
_TIER_TO_PRIORITY: dict[str, str] = {"quality": "best", "balanced": "balanced", "cost": "cheap"}


# Settings keys that carry the reasoning-EFFORT LEVEL a pick runs at, in the
# order we trust them. `effort` (Claude Code) / `intelligence` (Codex, OpenAI)
# hold the level directly; `thinking` is a fallback (a level on some surfaces, a
# bare On/Off toggle on others — filtered below).
_LEVEL_KEYS = ("effort", "intelligence", "thinking")
_NON_LEVEL_VALUES = frozenset({"on", "off", "n/a", "na", "none", ""})


def _reasoning_level(settings: dict[str, Any]) -> str | None:
    """The reasoning-effort LEVEL a pick runs at (e.g. `Max`, `XHigh`, `High`,
    `Ultracode`), read from its structured settings, or None when the surface
    carries no dial-able level (e.g. Cursor, whose thinking is a bare `On`).

    Dual-accepts both output contracts by construction: v2 puts the level in
    `effort`, v1 put it in `thinking`, and the toggle values v2 uses there
    (`On`/`Off`) are filtered out as non-levels."""
    for key in _LEVEL_KEYS:
        value = settings.get(key)
        if isinstance(value, str) and value.strip().lower() not in _NON_LEVEL_VALUES:
            return value.strip()
    return None


def _build_backup(result: dict[str, Any], access_guard: AccessGuard | None) -> BackupPick | None:
    """Enrich the Step 7 backup name into a BackupPick that adheres to the user's
    settings: the funded surface they run it on, plus its per-surface settings at
    the SAME reasoning posture as the pick (effort is a per-user axis, applied
    uniformly). Best-effort — platform/settings stay unset when unresolvable
    (anon / no funding), so the client falls back to showing just the model name.

    Called AFTER ``access_guard.enforce`` so it enriches the FINAL backup name
    (post-substitution), never a name the guard already replaced."""
    name = canonical_model_name(result.get("backup"))
    if not name:
        return None
    platform = access_guard.platform_for(name) if access_guard is not None else None
    settings: dict[str, Any] = {}
    if platform:
        level = _reasoning_level(result.get("settings") or {})
        if level is not None:
            # Ultracode is a Claude-Code session mode; on a cross-provider backup
            # it reads as that surface's top effort -> Max.
            thinking = "Max" if level.lower() == "ultracode" else level
            settings = _normalize_settings_contract(
                platform,
                _structured_settings(
                    {
                        "platform": platform,
                        "max_mode": "Off",
                        # `thinking` is the v1 input key _structured_settings
                        # reads the LEVEL from; `effort` is its v2 name. Pass
                        # both so this call keeps working across the package
                        # release that flips the contract (the package ships to
                        # prod separately from this service).
                        "thinking": thinking,
                        "effort": thinking,
                        "orchestration": "None",
                    }
                ),
            )
    return BackupPick(model=name, platform=platform, settings=settings)


def _pick_response(
    result: dict[str, Any],
    task_description: str,
    funding_guard: FundingGuard | None = None,
    access_guard: AccessGuard | None = None,
    priority: str = "balanced",
) -> RecommendResponse:
    """Build a RecommendResponse from one structured pick payload, computing its
    cost separately + best-effort (#164) so a cost-catalog miss degrades to "no
    cost panel" rather than failing the recommendation. Shared by the single-pick
    path and each rung of the ladder."""
    # Access-restriction guard (#445): if the engine picked a model outside the
    # user's declared access, substitute the best accessible one BEFORE cost /
    # settings / funding are derived, so every downstream field describes the
    # model actually returned. Mutates `result` in place; no-op when unset.
    if access_guard is not None:
        access_guard.enforce(result, priority)
    # Normalize an ACCEPTED pick to its catalog display name ("Claude Fable 5" ->
    # "Fable 5"): when the guard substitutes it's already canonical, but when it
    # accepts the engine's pick the raw maker-prefixed name would otherwise leak
    # to the UI. No-op for anon (still runs; catalog-only lookup).
    result["model"] = canonical_model_name(result.get("model"))
    session_cost_estimate, comparison_table = _session_cost(
        result["model"], result["platform"], task_description
    )
    rationale = result.get("rationale") or None
    rationale_sections = result.get("rationale_sections") or None
    # Funded-platform honesty guard (#444): rewrite a run-note that claims
    # subscription/$0 funding the requesting user never declared. Only active
    # when the per-user funding context was injected; pure text surgery.
    if funding_guard is not None:
        rationale, rationale_sections = funding_guard.sanitize(
            result["platform"], rationale, rationale_sections
        )
    return RecommendResponse(
        model=result["model"],
        platform=result["platform"],
        # Deterministic PLATFORM-CONDITIONAL settings shape (output contract v2):
        # dials the chosen surface does not expose are DROPPED, and a v1
        # effort-in-THINKING value is split into EFFORT + the On/Off toggle.
        settings=_normalize_settings_contract(result["platform"], result["settings"]),
        # Carry the model's reasoning across the service boundary (#173);
        # empty string -> None so the web edge falls back cleanly.
        rationale=rationale,
        # Carry the best-effort structured rationale sections (task/pick/effort) so
        # the web panel can render sub-headings; absent -> None and the edge
        # falls back to the raw `rationale` string above.
        rationale_sections=rationale_sections,
        # Carry the conversation-handling decision across the boundary (#190).
        conversation=result.get("conversation") or None,
        # Carry the fallback model (Step 7), enriched with its own funded platform
        # + per-surface settings so the backup adheres to the user's settings too.
        backup=_build_backup(result, access_guard),
        session_cost_estimate=session_cost_estimate,
        comparison_table=comparison_table,
    )


def recommend_ladder(req: RecommendRequest) -> LadderResponse:
    """One-call Cost/Balanced/Quality ladder (tasks #1/#3).

    Mirrors :func:`recommend` — same provider fallback chain, Gemini
    latency/output caps, and per-user funding + runtime-availability context —
    but calls the package's ``recommend_structured_ladder`` once and returns all
    three anchored picks plus the deterministic tier-distinctness ``guard``. The
    web edge calls this instead of fanning out three separate priority calls;
    on any provider/parse failure it raises (like ``recommend``) so the edge
    falls back to the fan-out.
    """
    last_error: Exception | None = None

    user_context_text = user_context_from_request(req.context)
    # Funded-platform honesty guard (#444) — same activation condition as the
    # per-user context above; applied to every rung of the ladder.
    funding_guard = funding_guard_from_request(req.context)
    # Access-restriction guard (#445) — applied per rung with that rung's
    # priority so substitutes are tier-appropriate (quality->best, cost->cheap).
    # Carries the operator's platform allow/deny list (Step A00) too, so every
    # rung is filtered and relabelled identically.
    access_guard = access_guard_from_request(req.context)
    unavailable_models = _unavailable_models_from_request(req.context)
    availability_authoritative = _availability_authoritative_from_request(req.context)
    # The user's permitted jurisdictions (or the baseline) — forwarded to the
    # package so the cross-provider backup substitution only picks a region-valid
    # fallback (0.2.20).
    allowed_jurisdictions = resolve_allowed_jurisdictions(req.context)

    for hint in _provider_chain(req.context):
        config = _config_for_hint(hint)
        is_gemini = config.provider == "google"
        is_frontier = is_gemini and config.model == _GEMINI_FRONTIER_MODEL
        is_openai_gpt5 = config.provider == "openai" and (config.model or "").startswith("gpt-5")
        if is_frontier:
            thinking_budget: int | None = _GEMINI_FRONTIER_THINKING_BUDGET
            # The ladder emits ~3x the visible tokens (three blocks), so lift the
            # per-call output cap accordingly to avoid truncating the third block.
            max_output_tokens: int | None = _ladder_output_cap(_GEMINI_FRONTIER_MAX_OUTPUT_TOKENS)
        elif is_gemini:
            thinking_budget = _GEMINI_THINKING_BUDGET
            max_output_tokens = _ladder_output_cap(_GEMINI_MAX_OUTPUT_TOKENS)
        elif is_openai_gpt5:
            # GPT-5 engine: minimal reasoning; lift the cap for the 3-block ladder.
            thinking_budget = _GPT5_THINKING_BUDGET
            max_output_tokens = _ladder_output_cap(_GPT5_MAX_OUTPUT_TOKENS)
        else:
            thinking_budget = None
            max_output_tokens = None
        temperature = _GEMINI_TEMPERATURE if is_gemini else None
        try:
            ladder = recommend_structured_ladder(
                req.task_description,
                config,
                user_context_text=user_context_text,
                unavailable_models=unavailable_models,
                availability_authoritative=availability_authoritative,
                allowed_jurisdictions=allowed_jurisdictions,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
                temperature=temperature,
            )
            picks = {
                tier: _pick_response(
                    pick,
                    req.task_description,
                    funding_guard,
                    access_guard,
                    _TIER_TO_PRIORITY.get(tier, "balanced"),
                )
                for tier, pick in ladder["picks"].items()
            }
            return LadderResponse(picks=picks, guard=ladder.get("guard", {}))
        except (MissingProviderKeyError, ProviderCallError, MalformedResponseError) as exc:
            last_error = exc
            if isinstance(exc, MalformedResponseError):
                logger.warning(
                    "provider hint %r returned an unparseable LADDER response; "
                    "falling through to the next provider in the chain",
                    hint,
                )
            continue

    if last_error is not None:
        raise last_error
    raise ProviderCallError("No provider available for ladder recommendation.")
