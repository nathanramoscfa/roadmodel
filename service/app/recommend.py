# service/app/recommend.py
from __future__ import annotations

import inspect
import logging
import os
from dataclasses import asdict, dataclass
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

from .engines import REGISTRY, EngineSpec
from .funding import (
    AccessGuard,
    FundingGuard,
    access_guard_from_request,
    canonical_model_name,
    funding_guard_from_request,
    platform_dials,
    resolve_allowed_jurisdictions,
    scoring_context_from_request,
    user_context_from_request,
)
from .models import BackupPick, LadderResponse, RecommendRequest, RecommendResponse

try:  # roadmodel >= 0.2.56; an older install meters nothing rather than failing
    from roadmodel import usage as engine_usage
except ImportError:  # pragma: no cover - exercised only against roadmodel < 0.2.56
    engine_usage = None

logger = logging.getLogger(__name__)

# roadmodel >= 0.2.59 reads the picks off the user's own frontier, from a
# user-context in the table format its scorer parses (scoring_context_from_request).
# An older install takes no such argument and keeps the engine's own picks.
_LADDER_TAKES_SCORING_CONTEXT = (
    "scoring_context_text" in inspect.signature(recommend_structured_ladder).parameters
)


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


# The engines the service can run, keyed by the force_provider hint the web
# edge sends: provider, API model id and per-call parameters all come from the
# registry (engines.json), which the web build reads too. Each entry's `notes`
# records why its parameters are what they are: Gemini 2.5 Flash runs thinking
# OFF (#132 latency) under a 512-token visible cap (#146 tail) at temperature 0
# (#176 determinism); the reasoning models (GPT-5+, Gemini 3, Claude) run at
# their reasoning floor with a generous cap, because reasoning tokens count
# against max_output_tokens and a tight cap returns no text at all; ladder mode
# emits three blocks, so its cap is about three single-block caps.
_PROVIDER_HINTS: dict[str, tuple[str, str]] = {
    hint: (spec.provider, spec.model) for hint, spec in REGISTRY.engines.items()
}

# The default chain: the default engine, then engines from the other providers,
# so a provider outage degrades to another provider instead of an error.
_FALLBACK_CHAIN: tuple[str, ...] = REGISTRY.fallback_chain


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
    """The engines to try, in order: the forced engine (the user's menu choice)
    first, then the fallback chain. An unknown hint is ignored, so a web build
    that names an engine this service does not know still gets an answer."""
    if not context:
        return _FALLBACK_CHAIN
    force = context.get("force_provider")
    if isinstance(force, str) and force in _PROVIDER_HINTS:
        rest = tuple(h for h in _FALLBACK_CHAIN if h != force)
        return (force, *rest)
    return _FALLBACK_CHAIN


def _spec_for(hint: str) -> EngineSpec:
    return REGISTRY.engines[hint]


def _reset_usage() -> None:
    if engine_usage is not None:
        engine_usage.reset()


def _call_usage() -> dict[str, Any] | None:
    """The provider-reported token counts of the engine call just made, or None
    when the installed roadmodel or the provider reported none."""
    if engine_usage is None:
        return None
    last = engine_usage.last()
    return dict(last.as_dict()) if last is not None else None


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
        thinking_budget, max_output_tokens, temperature = _spec_for(hint).params(ladder=False)
        try:
            # Inside the try: an engine whose provider key is missing raises
            # MissingProviderKeyError here, and the chain moves on to the next.
            config = _config_for_hint(hint)
            _reset_usage()
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
            response = _pick_response(
                result, req.task_description, funding_guard, access_guard, budget_priority
            )
            return response.model_copy(update={"engine": hint, "usage": _call_usage()})
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
    uniformly), or the surface and effort the pick's ``backup_plan`` names.
    Best-effort — platform/settings stay unset when unresolvable (anon / no
    funding), so the client falls back to showing just the model name.

    Called AFTER ``access_guard.enforce`` so it enriches the FINAL backup name
    (post-substitution), never a name the guard already replaced."""
    name = canonical_model_name(result.get("backup"))
    if not name:
        return None
    platform = access_guard.platform_for(name) if access_guard is not None else None
    level = _reasoning_level(result.get("settings") or {})
    # A frontier-ladder pick carries the platform and effort the scorer runs
    # its backup at (roadmodel >= 0.2.63): the user's subscription surface
    # where one reaches the model, at the pick's posture. Used only while the
    # backup is still the one it planned (the guard may have replaced it) and
    # the user can reach the model at all.
    plan = result.get("backup_plan")
    if (
        isinstance(plan, dict)
        and canonical_model_name(plan.get("model")) == name
        and isinstance(plan.get("platform"), str)
        and plan["platform"]
        and (access_guard is None or platform is not None)
    ):
        platform = plan["platform"]
        if isinstance(plan.get("effort"), str) and plan["effort"]:
            level = plan["effort"]
    settings: dict[str, Any] = {}
    if platform:
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
    planned_model = canonical_model_name(result.get("model"))
    if access_guard is not None:
        access_guard.enforce(result, priority)
    # Normalize an ACCEPTED pick to its catalog display name ("Claude Fable 5" ->
    # "Fable 5"): when the guard substitutes it's already canonical, but when it
    # accepts the engine's pick the raw maker-prefixed name would otherwise leak
    # to the UI. No-op for anon (still runs; catalog-only lookup).
    result["model"] = canonical_model_name(result.get("model"))
    # A category-specialist flag describes the model the package planned; a
    # model the guard substituted is no specialist.
    specialist = bool(result.get("specialist")) and result["model"] == planned_model
    specialist_category = result.get("specialist_category")
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
        specialist=specialist,
        specialist_category=(
            specialist_category if specialist and isinstance(specialist_category, str) else None
        ),
        session_cost_estimate=session_cost_estimate,
        comparison_table=comparison_table,
    )


@dataclass(frozen=True)
class _LadderInputs:
    """Everything a ladder call derives from the request, independent of the
    engine that answers it: built once, then shared by every attempt."""

    user_context_text: str | None
    funding_guard: FundingGuard | None
    access_guard: AccessGuard | None
    unavailable_models: list[str] | None
    availability_authoritative: bool
    allowed_jurisdictions: list[str]
    scoring_kwargs: dict[str, Any]


def _ladder_inputs(req: RecommendRequest) -> _LadderInputs:
    # The same declared access, in the format the package's scorer reads, so
    # the ladder table is drawn over the models this user can run.
    scoring_kwargs: dict[str, Any] = (
        {"scoring_context_text": scoring_context_from_request(req.context)}
        if _LADDER_TAKES_SCORING_CONTEXT
        else {}
    )
    return _LadderInputs(
        user_context_text=user_context_from_request(req.context),
        # Funded-platform honesty guard (#444) — same activation condition as
        # the per-user context above; applied to every rung of the ladder.
        funding_guard=funding_guard_from_request(req.context),
        # Access-restriction guard (#445) — applied per rung with that rung's
        # priority so substitutes are tier-appropriate (quality->best,
        # cost->cheap). Carries the operator's platform allow/deny list (Step
        # A00) too, so every rung is filtered and relabelled identically.
        access_guard=access_guard_from_request(req.context),
        unavailable_models=_unavailable_models_from_request(req.context),
        availability_authoritative=_availability_authoritative_from_request(req.context),
        # The user's permitted jurisdictions (or the baseline) — forwarded to
        # the package so the cross-provider backup substitution only picks a
        # region-valid fallback (0.2.20).
        allowed_jurisdictions=resolve_allowed_jurisdictions(req.context),
        scoring_kwargs=scoring_kwargs,
    )


def ladder_once(
    req: RecommendRequest, hint: str, config: Any, inputs: _LadderInputs | None = None
) -> LadderResponse:
    """ONE ladder call on ``config``, reported as engine ``hint``. Raises the
    package's errors unchanged: the operator path below catches them and moves
    down its fallback chain; the visitor path (visitor.py) maps them to an error
    code and stops, since a visitor's request runs on their key alone."""
    ins = inputs if inputs is not None else _ladder_inputs(req)
    thinking_budget, max_output_tokens, temperature = _spec_for(hint).params(ladder=True)
    _reset_usage()
    ladder = recommend_structured_ladder(
        req.task_description,
        config,
        user_context_text=ins.user_context_text,
        unavailable_models=ins.unavailable_models,
        availability_authoritative=ins.availability_authoritative,
        allowed_jurisdictions=ins.allowed_jurisdictions,
        max_output_tokens=max_output_tokens,
        thinking_budget=thinking_budget,
        temperature=temperature,
        **ins.scoring_kwargs,
    )
    picks = {
        tier: _pick_response(
            pick,
            req.task_description,
            ins.funding_guard,
            ins.access_guard,
            _TIER_TO_PRIORITY.get(tier, "balanced"),
        )
        for tier, pick in ladder["picks"].items()
    }
    return LadderResponse(
        picks=picks,
        guard=ladder.get("guard", {}),
        engine=hint,
        usage=_call_usage(),
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
    inputs = _ladder_inputs(req)

    for hint in _provider_chain(req.context):
        try:
            config = _config_for_hint(hint)
            return ladder_once(req, hint, config, inputs)
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
