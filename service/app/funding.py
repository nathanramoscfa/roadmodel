# service/app/funding.py
#
# Build a PER-USER user-context string from the requesting user's declared
# funding (held subscriptions + enabled API providers) so the recommendation
# LLM's model SELECTION can honor it (Phase 4.8 T2b, issues #260 / #163).
#
# The roadmodel package builds the recommender's system prompt from a
# user-context document (src/roadmodel/data/user-context.example.md format).
# Today the service feeds a single STATIC bundled template for every request,
# so per-user funding never reaches model selection. roadmodel 0.2.6 added an
# optional `user_context_text` override to recommend_structured(); this module
# produces that text from the request context.
#
# Everything here is CATALOG-DERIVED (no hardcoded provider/funding lists) and
# mirrors the TS funding logic at web/lib/{subscriptions,api-providers,funding}.ts
# so the ids the web stores resolve identically here:
#   - subscription ids come from getSubscriptionOptions() == tierId(provider,tier)
#     (LEGACY_IDS + slugify), so _tier_id() below is a faithful port.
#   - api_providers are catalog access_methods[].provider ids (lowercase).
#
# roadmodel NEVER stores the user's API keys — api_providers is a per-provider
# boolean SIGNAL only. The anon / no-funding path returns None so the caller
# falls back to the bundled template unchanged.
from __future__ import annotations

import json
import logging
import os
import re
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

# The pool-aggregator provider set (Cursor) — SHARED with the package's
# roadmodel.cost.model_provider so this service-side maker resolution can never
# drift from it (the drift was the aggregator-maker backup bug).
from roadmodel.cost import _AGGREGATOR_PROVIDERS  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_BUNDLED_CATALOG_PATH: Traversable = resources.files("roadmodel.data") / "catalog.json"

# Billing kinds reachable with the user's OWN API key / pay-per-token. Mirrors
# web/lib/api-providers.ts API_BILLING. `subscription-included` and
# `subscription-pool` are subscription-only and are NOT an API path.
_API_BILLING: frozenset[str] = frozenset({"per-token", "subscription-or-key"})

# Display names for known providers (mirror web/lib/api-providers.ts); the
# fallback capitalizes the id so a newly-federated provider still renders.
_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "cursor": "Cursor",
    "zai": "z.ai",
}

# Leading maker / product-line words an engine may prepend to a bare catalog
# name ("Claude Fable 5" for catalog "Fable 5"). Stripped on a resolve MISS
# (direct match is always tried first) so a correctly-named, accessible pick is
# not misread as inaccessible — which triggered a bogus self-substitution and
# the self-contradictory "<pick> is strongest; <pick> was outside your access"
# rationale (the pick and its "substitute" were the same model under two names).
_VENDOR_NAME_PREFIXES: tuple[str, ...] = (
    "claude ",
    "gemini ",
    "anthropic ",
    "openai ",
    "google ",
    "mistral ",
    "deepseek ",
    "xai ",
)

# Stable ids for the three pre-#152 subscription tiers (mirror web/lib/
# subscriptions.ts LEGACY_IDS). Keyed by `${provider}|${tier}`.
_LEGACY_TIER_IDS: dict[str, str] = {
    "Anthropic|claude.ai Max ($200)": "claude-max",
    "Cursor|Cursor Ultra": "cursor-ultra",
    "OpenAI|ChatGPT Pro ($200)": "chatgpt-pro",
}

# Default allowed-jurisdictions baseline (mirror the selector's documented
# default `[us, eu, uk, ca, au, jp, kr]`).
_BASELINE_JURISDICTIONS: tuple[str, ...] = ("us", "eu", "uk", "ca", "au", "jp", "kr")

_DEFAULT_BUDGET_PRIORITY = "balanced"

# The budget-priority posture is the user's quality-vs-cost lever (Cost /
# Balanced / Quality on /recommend, stored as the historical ids cheap /
# balanced / best). It is the ONE place the per-request budget choice changes
# model SELECTION: each posture hands the selector a DIFFERENT quality-vs-cost
# rule. The text is self-asserting as an OVERRIDE of the selector objective's
# default quality-first posture, so the lever takes effect from this appended
# user-context alone — even before the matching docs/model-selector.txt
# <objective> "BUDGET-PRIORITY OVERRIDE" clause ships in a roadmodel release.
# Unknown / legacy ids fall back to the balanced posture so a bad value never
# crashes or silently hard-codes one extreme.
#
# COST BY TIER + EFFORT, NOT JUST PRICE: when the user funds a whole family at
# $0 (the **Active subscriptions** section above, e.g. claude.ai Max), the
# out-of-pocket price is FLAT across every candidate, so price alone cannot
# differentiate the three priorities — left to price, the selector held the
# FRONTIER $0 model for Cost, Balanced, and Quality alike (the all-Max collapse:
# Cost==Quality at max effort). So the Cost posture differentiates by CAPABILITY
# TIER and EFFORT: the smallest / lowest-tier ADEQUATE model at the lowest
# clearing effort, landing clearly BELOW the Quality pick — not the top $0 model.
# It only drops to a per-token model when that is genuinely cheaper AND adequate.
_BUDGET_POSTURE: dict[str, str] = {
    "cheap": (
        "minimize the RESOURCES this task consumes — the real cost signal even "
        "when out-of-pocket price is $0. When several models are funded at $0 "
        "(e.g. a whole family via one subscription like claude.ai Max), price is "
        "FLAT across them and cannot be the tie-breaker, so differentiate by "
        "CAPABILITY TIER and EFFORT: pick the SMALLEST / lowest-tier model that "
        "is still an ADEQUATE fit for this task (a mid-tier model over a frontier "
        "one when the mid-tier clears the bar), at the LOWEST reasoning effort / "
        "thinking level that still clears it. Do NOT keep the most capable model "
        "just because it is also $0-funded — that is the Quality pick; the Cost "
        "pick MUST land clearly BELOW it in capability tier and effort. Only "
        "switch to a cheaper-tier model the user pays per-token for when it is "
        "genuinely cheaper in real dollars AND adequate. Never emit the top "
        "`max` effort; never over-buy tier or effort beyond what the task needs."
    ),
    "balanced": (
        "recommend the best VALUE, landing BETWEEN the Cost and Quality picks in "
        "capability and effort — a model whose quality is well-matched to the "
        "task's difficulty, at a sensible (not maxed-out) reasoning effort. "
        "Prefer a $0-funded model from the **Active subscriptions** section above "
        "when it is competitive, and prefer the cheaper option when two models "
        "are CLOSE in expected quality (not only on an exact tie); reserve the "
        "most expensive tiers and top effort levels for tasks that require them."
    ),
    "best": (
        "recommend the HIGHEST-QUALITY outcome for this task, regardless of cost: "
        "the best-fit model at its highest USEFUL reasoning effort (e.g. `xhigh` "
        "/ `max` where the model and surface support it). When the best-fit model "
        "is $0-funded the user is spending only session budget, so do NOT hold "
        "effort back. Quality wins outright; cost only breaks an exact quality "
        "tie."
    ),
}


def _budget_block(budget: str, *, flat_funding: bool = False) -> str:
    """Render the value-dependent budget-priority posture for the user-context.

    ``budget`` is echoed verbatim in the bold header so the persisted id is
    visible, while the POSTURE sentence (the part the selector acts on) is keyed
    off it via _BUDGET_POSTURE — unknown ids degrade to the balanced posture.

    ``flat_funding`` appends the gate's precedence note (mirroring the selector's
    "SUSPENDED by the FLAT-FUNDING GATE below when it applies"), so the posture
    can never be read as contradicting the gate block rendered underneath it.
    """
    posture = _BUDGET_POSTURE.get(budget, _BUDGET_POSTURE["balanced"])
    suspension = (
        " NOTE: the FLAT-FUNDING GATE below applies to THIS request and takes "
        "precedence over this posture — its tier-down and effort-down parts are "
        "SUSPENDED wherever the gate is open."
        if flat_funding
        else ""
    )
    return (
        f"**Budget priority:** {budget} — this is the user's explicit "
        f"quality-vs-cost instruction for THIS request and OVERRIDES any default "
        f"quality-first posture in the selector objective. For this request, "
        f"{posture} On a quality tie a $0 held subscription beats new "
        f"pay-per-token spend; treat the subscriptions above as sunk cost."
        f"{suspension}"
    )


# --- Flat-funding gate (tier axis) ------------------------------------------
#
# Scaling the capability TIER down, or the reasoning EFFORT down, is only worth
# doing when it SAVES the user something — and under a flat subscription it does
# not. When one plan funds the whole candidate family at the SAME $0 marginal
# price, out-of-pocket price is FLAT across every tier, so tiering down buys the
# user nothing and costs real quality. This is the service-side half of the
# selector's <objective> FLAT-FUNDING GATE; the two are written to agree, and
# this one is SELF-ASSERTING (it declares its own precedence) so the gate takes
# effect from this appended user-context alone — even before the matching
# docs/model-selector.txt clause ships in a roadmodel release. Mirrors the
# budget-posture and consumption-headroom precedents above.
#
# Service-side gate condition (the engine re-checks family coverage per
# candidate, which is the part only it can see):
#   (a) the user holds >= 1 subscription that funds >= 1 access-method surface
#       at $0 marginal (the **Active subscriptions** section is non-empty), AND
#   (b) the effective consumption headroom is `uncapped` — i.e. the user does
#       not exhaust that plan's budget, so consumption is not a real cost. A
#       `capped` plan keeps the gate CLOSED: there, tiering/effort down really
#       does conserve a budget the user can hit.
# Anything else — per-token paths, an exhausted/capped budget, a candidate set
# straddling funded and unfunded models — leaves the budget posture unchanged.


def _flat_funding_block() -> str:
    """The self-asserting FLAT-FUNDING GATE, rendered only when the gate is open."""
    return (
        "**Flat funding (GATE OPEN):** the subscriptions above fund their whole "
        "covered model family at the SAME $0 marginal price and this user does "
        "not exhaust that budget, so out-of-pocket price is FLAT across the "
        "candidates and CANNOT differentiate them. This gate has the HIGHEST "
        "precedence for this request — it OVERRIDES the budget priority above on "
        "BOTH the capability-TIER and the reasoning-EFFORT axis whenever the "
        "chosen PLATFORM is subscription-funded, the candidate model family is "
        "COVERED by that same subscription, and the budget is not reported "
        "exhausted:\n"
        "- HOLD the capability TIER — recommend the model the task actually "
        "warrants, on EVERY priority INCLUDING Cost. Do NOT down-tier to a "
        "smaller model on cost grounds when the stronger model is funded at the "
        "same $0.\n"
        "- DEFAULT the reasoning EFFORT to the TOP USEFUL rung the model + "
        "surface support (`max`, or the surface's top step where there is no "
        "`max`), on EVERY priority INCLUDING Cost. The Cost posture's "
        '"never emit the top `max` effort" floor is SUSPENDED outright.\n'
        "- DIFFERENTIATE the three priorities on the axes that still cost "
        "something — LATENCY (a smaller/faster model when the user is waiting on "
        "it), CONTEXT (a model whose native window fits the task without "
        "truncation), and BLAST RADIUS (a narrower-scoped or more steerable pick "
        "for an autonomous, hard-to-review change) — never on a price that is "
        "identical across the set.\n"
        "- If, after applying those axes, two or more priorities land on the SAME "
        "model and settings, EMIT THEM AS THE SAME PICK and SAY SO in the "
        'RATIONALE ("flat funding — same $0 marginal cost at every tier, so Cost '
        'and Quality converge here"). NEVER manufacture an artificial spread by '
        "recommending a model the task does not warrant.\n"
        "The gate is CLOSED for any pay-per-token path, an exhausted subscription "
        "budget, or a candidate that the subscriptions above do not cover — there "
        "the budget priority applies UNCHANGED, because tiering down saves real "
        "dollars."
    )


# --- Consumption headroom (effort axis) -------------------------------------
#
# Reasoning EFFORT and capability TIER are two separate axes. The budget-priority
# posture above scales BOTH down the Cost/Balanced/Quality ladder, but scaling
# effort only helps when effort actually COSTS the user something — per-token
# dollars, a usage cap they can exhaust, or latency they value. A user on a
# top-tier flat subscription who never exhausts the budget and does not value
# speed pays NOTHING for max effort, so scaling it down on the Cost pick buys
# them nothing and only lowers quality. This posture governs the effort axis
# ORTHOGONALLY to which model is chosen.
#
# Hybrid activation (matches the Settings control):
#   - `uncapped` / `capped`: explicit user override, honored as-is.
#   - `auto` (default): DERIVE from funded tiers — a subscription in the top
#     consumer price band (>= $200/mo, the "maximum available under consumer
#     subscriptions") resolves to `uncapped`; anything else (lower sub, or
#     per-token only) stays `capped`, the conservative behavior-unchanged default.
# Only the behavior-CHANGING `uncapped` posture is rendered into the context
# (see _consumption_block); `capped` is the selector's existing default, so it
# emits nothing and keeps the prompt lean.
_TOP_TIER_MONTHLY_USD: float = 200.0

_CONSUMPTION_HEADROOM_VALUES: frozenset[str] = frozenset({"auto", "uncapped", "capped"})


def _effective_consumption_headroom(stored: str | None, sub_set: set[str], tiers: Any) -> str:
    """Resolve the stored headroom setting to an effective posture (`uncapped` /
    `capped`). Explicit values pass through; `auto` (or any unknown/absent value)
    derives from the user's funded subscription tiers — `uncapped` iff one sits in
    the top consumer price band, else `capped` (conservative)."""
    value = (stored or "auto").strip().lower()
    if value == "uncapped":
        return "uncapped"
    if value == "capped":
        return "capped"
    # auto (and any unrecognized value): derive from funded-tier prices.
    for tier in tiers:
        provider = tier.get("provider")
        name = tier.get("tier")
        if not isinstance(provider, str) or not isinstance(name, str):
            continue
        if _tier_id(provider, name) not in sub_set:
            continue
        try:
            monthly = float(tier.get("monthly_usd") or 0.0)
        except (TypeError, ValueError):
            monthly = 0.0
        if monthly >= _TOP_TIER_MONTHLY_USD:
            return "uncapped"
    return "capped"


def _consumption_block(*, flat_funding: bool = False) -> str:
    """The self-asserting `uncapped` consumption-headroom posture. Rendered only
    when the effective posture is `uncapped` (the behavior-changing case), so it
    takes effect from the appended user-context alone — even before the matching
    docs/model-selector.txt <objective> "CONSUMPTION-HEADROOM OVERRIDE" clause
    ships in a roadmodel release (mirrors the budget-posture precedent).

    ``flat_funding`` swaps the final differentiation sentence: this posture owns
    the EFFORT axis and the FLAT-FUNDING GATE owns the TIER axis, and the two
    COMPOSE. With the gate CLOSED the picks still differ by capability tier
    alone; with it OPEN the tier ladder is held too, so saying "differ by tier
    alone" here would flatly contradict the gate block above it."""
    if flat_funding:
        differentiation = (
            "The FLAT-FUNDING GATE above additionally HOLDS the capability TIER, "
            "so the three picks differentiate on latency / context / blast radius "
            "rather than on tier or effort — and may legitimately CONVERGE, which "
            "the RATIONALE must then state outright."
        )
    else:
        differentiation = (
            "The Cost/Balanced/Quality picks must still differ, but by CAPABILITY "
            "TIER ALONE (Cost = the smallest adequate model at MAX effort; "
            "Quality = the frontier model at MAX effort), NOT by effort."
        )
    return (
        "**Consumption headroom:** uncapped — this user runs a flat subscription "
        "whose usage budget they do not exhaust, so spending more reasoning EFFORT "
        "costs them nothing (no per-token dollars, no usage cap they hit, latency "
        "not valued). This OVERRIDES the effort-scaling in the budget priority "
        "above on the reasoning-effort / thinking-LEVEL axis ONLY: emit the "
        "HIGHEST USEFUL reasoning effort the model + surface support (top of the "
        "effort dial — `max`, or `xhigh` where the model has no `max` step) on ALL "
        "THREE priorities INCLUDING Cost, and keep extended thinking ON (never "
        f"emit an Off thinking / effort). {differentiation} This changes only how "
        "much effort each pick runs at, never WHICH model is chosen."
    )


def load_catalog() -> dict[str, Any]:
    """Load the catalog (env override -> bundled), mirroring roadmodel.cost.

    Honors ``ROADMODEL_CATALOG_PATH`` so tests can drive a fixture catalog;
    otherwise reads the catalog bundled in the pinned roadmodel package.
    """
    override = os.environ.get("ROADMODEL_CATALOG_PATH")
    if override:
        text = Path(override).expanduser().read_text(encoding="utf-8")
    else:
        text = _BUNDLED_CATALOG_PATH.read_text(encoding="utf-8")
    parsed: object = json.loads(text)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def canonical_model_name(
    model_ref: str | None, *, catalog: dict[str, Any] | None = None
) -> str | None:
    """Map an engine-emitted model name to its catalog DISPLAY name.

    The engine sometimes prepends a maker/product-line word ("Claude Fable 5"
    for catalog "Fable 5"); normalizing accepted picks to the catalog name keeps
    the UI consistent with how the model is named everywhere else. Tolerates a
    leading vendor prefix (mirrors AccessGuard._resolve_id) and matches on id too.
    Returns the ref UNCHANGED when it doesn't resolve — never invents or drops a
    name, so an unknown/new model still shows exactly what the engine emitted.
    """
    if not model_ref:
        return model_ref
    cat = catalog if catalog is not None else load_catalog()
    index: dict[str, str] = {}
    for model in cat.get("models", []) or []:
        name = model.get("name")
        if not isinstance(name, str):
            continue
        index[name.strip().lower()] = name
        mid = model.get("id")
        if isinstance(mid, str):
            index[mid.strip().lower()] = name
    key = model_ref.strip().lower()
    if key in index:
        return index[key]
    for prefix in _VENDOR_NAME_PREFIXES:
        if key.startswith(prefix):
            hit = index.get(key[len(prefix) :].strip())
            if hit is not None:
                return hit
    return model_ref


# --- Platform dial exposure (output contract v2) -----------------------------
#
# Output-contract v2 made every runtime-setting field PLATFORM-CONDITIONAL: a
# block emits EFFORT / THINKING only where the access method's
# `exposes_thinking` is `yes`, and MAX MODE only where `exposes_max_mode` is
# `yes`. A dial the surface lacks means the LINE IS ABSENT — never `Off`, never
# `N/A`. The catalog already carries both attributes, so the service reads them
# from there instead of hard-coding platform names (which drifted: a
# hard-coded set force-reverted Cursor's package-owned thinking value in #387,
# and the revert then silently came back in #389).
#
# UNKNOWN is a third state on purpose: a platform the catalog does not describe
# (or an attribute it omits) leaves the dial ABSENT from the map, and the caller
# then leaves those settings untouched — fail-open, never invent a shape.
_DIAL_ATTRS: dict[str, str] = {"thinking": "exposes_thinking", "max_mode": "exposes_max_mode"}

# Pre-catalog fallback: the two surfaces that expose no reasoning dial today.
# Used only when the catalog cannot be read, so a load failure degrades to the
# previously hard-coded knowledge rather than to no normalization at all.
_DIAL_FALLBACK: dict[str, dict[str, bool]] = {
    "cursor": {"thinking": False, "max_mode": True},
    "xai-api": {"thinking": False, "max_mode": False},
    "xai api": {"thinking": False, "max_mode": False},
}

# Catalog-derived dial map, cached per catalog source (the ROADMODEL_CATALOG_PATH
# override, or "" for the bundled one) so a warm Function never re-parses the
# ~200KB catalog on the request path, while tests pointing at a fixture catalog
# still get their own entry.
_DIAL_CACHE: dict[str, dict[str, dict[str, bool]]] = {}


def _build_dial_map(catalog: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Index access methods by lowercased id AND display name -> exposed dials."""
    dials: dict[str, dict[str, bool]] = {}
    for method in catalog.get("access_methods", []) or []:
        entry: dict[str, bool] = {}
        for dial, attr in _DIAL_ATTRS.items():
            raw = method.get(attr)
            if isinstance(raw, str) and raw.strip().lower() in {"yes", "no"}:
                entry[dial] = raw.strip().lower() == "yes"
        if not entry:
            continue
        for key in (method.get("id"), method.get("name")):
            if isinstance(key, str) and key.strip():
                dials[key.strip().lower()] = entry
    return dials


def platform_dials(platform: str, *, catalog: dict[str, Any] | None = None) -> dict[str, bool]:
    """Which runtime dials an access method EXPOSES, keyed `thinking`/`max_mode`.

    A missing key means "unknown" (the catalog does not describe this platform,
    or omits the attribute) — callers must leave the corresponding setting
    untouched rather than guess. Never raises: a catalog failure degrades to the
    small known-surfaces fallback.
    """
    if catalog is not None:
        return _build_dial_map(catalog).get(platform.strip().lower(), {})
    key = os.environ.get("ROADMODEL_CATALOG_PATH", "")
    cached = _DIAL_CACHE.get(key)
    if cached is None:
        try:
            cached = _build_dial_map(load_catalog()) or dict(_DIAL_FALLBACK)
        except Exception:  # noqa: BLE001 - dial lookup is best-effort, never fatal
            logger.warning("platform dial map build failed (non-fatal)", exc_info=True)
            cached = dict(_DIAL_FALLBACK)
        _DIAL_CACHE[key] = cached
    return cached.get(platform.strip().lower(), {})


def _slugify(value: str) -> str:
    # Faithful port of web/lib/subscriptions.ts slugify(); ORDER MATTERS.
    value = value.lower()
    value = value.replace("+", " plus")  # keep "Pro" vs "Pro+" distinct
    value = re.sub(r"\(\$(\d+)\)", r"\1", value)  # "($200)" -> "200"
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"^-+|-+$", "", value)
    return value


def _clean_label(tier: str) -> str:
    # Mirror web/lib/subscriptions.ts cleanLabel(): "claude.ai Max" -> "Claude Max".
    return re.sub(r"claude\.ai Max", "Claude Max", tier, flags=re.IGNORECASE)


def _display_label(tier: str) -> str:
    # Clean label + strip the " ($NNN)" price disambiguator for display, matching
    # the web Settings picker (web/lib/funding.ts SUB_LABEL). The price tier does
    # not affect funded surfaces, so "Claude Max ($100)"/"($200)" both read as
    # "Claude Max" — what the user actually chose in Settings.
    return re.sub(r"\s*\(\$[\d.,]+\)\s*$", "", _clean_label(tier))


def _tier_id(provider: str, tier: str) -> str:
    legacy = _LEGACY_TIER_IDS.get(f"{provider}|{tier}")
    if legacy is not None:
        return legacy
    return _slugify(f"{provider} {_clean_label(tier)}")


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider) or (provider[:1].upper() + provider[1:])


def _str_list(value: object) -> list[str]:
    """Coerce a context value to a list of strings, dropping non-strings."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


# --- Platform allowlist / denylist (selector <access-selection> Step A00) ----
#
# The operator may declare which access METHODS they will actually operate:
#   - platforms_allowed  — when non-empty, ONLY these access-method ids are usable.
#   - platforms_excluded — access-method ids the operator has opted out of.
# Both are HARD filters applied BEFORE any scoring (unlike the SOFT platform
# preference ORDER), and they OUTRANK the "never hard-exclude an unfunded access
# method" guardrail: unfunded means "costs money the user may still choose to
# spend", excluded means "produces settings the user cannot apply".
#
# An ABSENT or EMPTY allowlist means "no opt-out declared" — NEVER "allow
# nothing". Every helper below treats an empty list as unset, so a missing field
# can never silently zero out the accessible set (the same defensive shape as
# allowed_jurisdictions, which falls back to the documented baseline).


def _platform_id_set(values: list[str] | None) -> set[str]:
    """Normalize a declared platform list to lowercase ids, dropping blanks."""
    return {v.strip().lower() for v in (values or []) if isinstance(v, str) and v.strip()}


def _method_permitted(method_id: object, allowed: set[str], excluded: set[str]) -> bool:
    """Whether one access METHOD survives the operator's allow/deny list."""
    if not allowed and not excluded:
        return True  # nothing declared -> no-op, never "allow nothing"
    if not isinstance(method_id, str):
        # An unidentifiable method can't be matched against an allowlist, so it
        # survives only in deny-list-only mode (fail-open on a malformed entry).
        return not allowed
    mid = method_id.strip().lower()
    if mid in excluded:
        return False
    return not allowed or mid in allowed


def known_platform_ids(catalog: dict[str, Any] | None = None) -> set[str]:
    """Lowercased access-method ids the catalog actually describes."""
    try:
        cat = catalog if catalog is not None else load_catalog()
    except Exception:  # pragma: no cover - catalog load already fails soft elsewhere
        return set()
    known: set[str] = set()
    for method in cat.get("access_methods", []) or []:
        mid = method.get("id")
        if isinstance(mid, str) and mid.strip():
            known.add(mid.strip().lower())
    return known


def _known_platforms_only(values: list[str], known: set[str], field: str) -> list[str]:
    """Drop declared platform ids the catalog does not describe.

    These values arrive in the request body and are rendered VERBATIM into the
    user-context document that becomes the engine's system prompt, so they are
    constrained to a closed, catalog-derived vocabulary rather than passed
    through as free text. This mirrors how `api_providers` is validated against
    a catalog-derived set server-side instead of trusting the client, and it
    also makes a typo'd id a no-op rather than something that empties the
    accessible set and trips the fail-safe. An empty ``known`` set means the
    catalog could not be read; pass the values through unchanged rather than
    silently discarding a legitimate filter.
    """
    if not known:
        return values
    kept = [v for v in values if v.strip().lower() in known]
    dropped = [v for v in values if v.strip().lower() not in known]
    if dropped:
        logger.warning(
            "ignoring unknown %s entries not present in the catalog: %s", field, sorted(dropped)
        )
    return kept


def resolve_platform_filters(
    context: dict[str, Any] | None, *, catalog: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    """The request's declared (platforms_allowed, platforms_excluded).

    Read with the same defensive ``_str_list`` treatment as
    ``allowed_jurisdictions``; an absent / malformed field yields an EMPTY list,
    which every consumer reads as "unset" (no filtering), not "allow nothing".
    Entries are then narrowed to ids the catalog actually describes, so an
    arbitrary client-supplied string never reaches the prompt or the filter."""
    ctx = context or {}
    known = known_platform_ids(catalog)
    allowed = _known_platforms_only(
        _str_list(ctx.get("platforms_allowed")), known, "platforms_allowed"
    )
    excluded = _known_platforms_only(
        _str_list(ctx.get("platforms_excluded")), known, "platforms_excluded"
    )
    return allowed, excluded


# --- Accessible-model set (access restriction, #445) ------------------------
#
# When the user has declared any funding, the recommender must recommend ONLY
# models the user can actually run: reachable via an enabled API provider
# (pay-per-token with their own key) or a held-subscription surface, AND in an
# allowed jurisdiction. This computes that set; the caller feeds the names into
# the user-context as a hard allowlist (bias) and the AccessGuard enforces it
# deterministically after the pick (hard guarantee).


def _funded_surface_ids(tiers: Any, sub_set: set[str]) -> set[str]:
    """Access-method ids funded at $0 by the user's held subscriptions."""
    funded: set[str] = set()
    for tier in tiers:
        provider = tier.get("provider")
        name = tier.get("tier")
        if not isinstance(provider, str) or not isinstance(name, str):
            continue
        if _tier_id(provider, name) not in sub_set:
            continue
        funded.update(s for s in (tier.get("surface_funded") or []) if isinstance(s, str))
    return funded


def accessible_model_ids(
    subscriptions: list[str],
    api_providers: list[str],
    *,
    allowed_jurisdictions: list[str] | None = None,
    platforms_allowed: list[str] | None = None,
    platforms_excluded: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
) -> set[str] | None:
    """Model ids the user can actually run, or ``None`` for "no restriction".

    A model qualifies when some access method that supports it is reachable by
    the user — an API-billing method whose provider is enabled, or a
    subscription surface the user funds — AND that method survives the
    operator's platform allow/deny list (Step A00) AND the model's jurisdiction
    is allowed. Returns ``None`` (no funding declared) so the caller skips the
    filter entirely (anon / free path unchanged). Never raises.

    This loop is the ONE place a platform id is accepted (``method["id"]``), so
    applying the allow/deny filter here propagates it to BOTH consumers of the
    accessible set: the user-context allowlist that BIASES the engine, and the
    deterministic AccessGuard that ENFORCES the pick. The #444 lesson — prompt
    bias alone is not adherence — is why the filter belongs at this choke point
    and not only in the prompt prose.
    """
    api_set = {p for p in api_providers if isinstance(p, str)}
    sub_set = {s for s in subscriptions if isinstance(s, str)}
    if not api_set and not sub_set:
        return None
    cat = catalog if catalog is not None else load_catalog()
    methods: Any = cat.get("access_methods", []) or []
    tiers: Any = cat.get("subscription_tiers", []) or []
    models: Any = cat.get("models", []) or []

    funded_surface_ids = _funded_surface_ids(tiers, sub_set)
    allowed = {j.strip().lower() for j in (allowed_jurisdictions or _BASELINE_JURISDICTIONS)}

    def _resolve(allow: set[str], deny: set[str]) -> set[str]:
        reachable_model_ids: set[str] = set()
        for method in methods:
            provider = method.get("provider")
            mid = method.get("id")
            if not _method_permitted(mid, allow, deny):
                continue
            by_api = method.get("billing") in _API_BILLING and provider in api_set
            by_sub = isinstance(mid, str) and mid in funded_surface_ids
            if not (by_api or by_sub):
                continue
            for supported in method.get("supports_models") or []:
                if isinstance(supported, str):
                    reachable_model_ids.add(supported)

        resolved: set[str] = set()
        for model in models:
            model_id = model.get("id")
            if not isinstance(model_id, str) or model_id not in reachable_model_ids:
                continue
            juris = str(model.get("jurisdiction", "")).strip().lower()
            if juris and juris not in allowed:
                continue
            resolved.add(model_id)
        return resolved

    allow_platforms = _platform_id_set(platforms_allowed)
    deny_platforms = _platform_id_set(platforms_excluded)
    accessible = _resolve(allow_platforms, deny_platforms)

    # FAIL SAFE: a platform filter that empties an otherwise non-empty accessible
    # set is a misconfiguration (a stale/typo'd id, or a list naming only
    # surfaces this user doesn't fund). Producing ZERO recommendations from it
    # would be strictly worse than ignoring it, so fall back to the unfiltered
    # set and log the drop instead. The jurisdiction filter deliberately does NOT
    # get this treatment — it is a compliance constraint, this one is a
    # preference.
    if (allow_platforms or deny_platforms) and not accessible:
        unfiltered = _resolve(set(), set())
        if unfiltered:
            logger.warning(
                "platform filter emptied the accessible set (allowed=%s excluded=%s); "
                "falling back to the unfiltered set",
                sorted(allow_platforms),
                sorted(deny_platforms),
            )
            return unfiltered
    return accessible


def _accessible_model_names(accessible_ids: set[str], catalog: dict[str, Any]) -> list[str]:
    """Catalog display names for accessible ids, in catalog order (stable)."""
    names: list[str] = []
    for model in catalog.get("models", []) or []:
        mid = model.get("id")
        if isinstance(mid, str) and mid in accessible_ids:
            name = model.get("name")
            names.append(name if isinstance(name, str) else mid)
    return names


def _access_restriction_block(accessible_names: list[str]) -> str:
    """The hard allowlist section appended to the user-context (#445 bias)."""
    if accessible_names:
        listed = ", ".join(accessible_names)
        return (
            "**Access restriction (HARD):** recommend ONLY models the user can "
            "actually run given the access declared above. For THIS request the "
            f"ONLY permitted models are: {listed}. Every MODEL and BACKUP you "
            "emit MUST be one of these — never recommend any model outside this "
            "list, even if a stronger model exists, because the user has no way "
            "to run it. If none is a perfect fit, pick the closest one from the "
            "list and say so. This overrides the selector's default frontier-"
            "first posture."
        )
    return (
        "**Access restriction (HARD):** the user's declared access resolves to "
        "NO catalogued model in an allowed jurisdiction. Recommend the closest "
        "single model to the task and state plainly that it is outside the "
        "user's declared access, so they can enable a provider that can run it."
    )


def _platforms_block(allowed: list[str], excluded: list[str]) -> str:
    """The operator's platform allow/deny list, as the selector's Step A00 states
    it. Rendered ONLY when at least one list is declared (an absent list is a
    no-op, and the default path must not pay for prose that says nothing)."""
    lines: list[str] = []
    if allowed:
        lines.append(
            "**Allowed platforms (HARD):** `platforms.allowed` — the operator "
            f"will only operate these access methods: `{', '.join(allowed)}`. "
            "DROP every access method whose id is not in that list before any "
            "scoring; never recommend a PLATFORM outside it."
        )
    if excluded:
        lines.append(
            "**Excluded platforms (HARD):** `platforms.excluded` — the operator "
            f"has opted OUT of these access methods: `{', '.join(excluded)}`. "
            "DROP every one of them before any scoring; never recommend one as "
            "the PLATFORM."
        )
    lines.append(
        "These are HARD filters applied BEFORE scoring, exactly like the "
        "jurisdiction filter and unlike the SOFT platform preference ORDER above. "
        "They OUTRANK the guardrail that says never to hard-exclude an UNFUNDED "
        'access method: unfunded means "costs money the user may still choose to '
        'spend", while excluded means "produces settings the user cannot apply" — '
        "so never re-admit an excluded platform on the grounds that it is merely "
        "unfunded. DISCLOSURE: when a dropped platform would otherwise have won, "
        "add ONE clause to the RATIONALE naming it and the fact that the "
        "operator's list excluded it (e.g. \"Cursor would rank first on pool "
        'economics but is not in the declared platform allowlist"). If the filter '
        "leaves no method that reaches the model, say so plainly in the RATIONALE "
        "rather than silently re-admitting a dropped one."
    )
    return "\n\n".join(lines)


def build_user_context(
    subscriptions: list[str],
    api_providers: list[str],
    *,
    budget_priority: str | None = None,
    consumption_headroom: str | None = None,
    allowed_jurisdictions: list[str] | None = None,
    platforms_allowed: list[str] | None = None,
    platforms_excluded: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
) -> str | None:
    """Render the user's declared funding as a roadmodel user-context document.

    Returns None when the user has declared no funding that resolves against
    the catalog (e.g. anon requests, or only stale ids) — the caller then
    passes ``user_context_text=None`` and the bundled template is used, leaving
    behavior unchanged. Catalog-derived; never stores or echoes API keys.
    """
    cat = catalog if catalog is not None else load_catalog()
    tiers: Any = cat.get("subscription_tiers", []) or []
    methods: Any = cat.get("access_methods", []) or []

    method_name: dict[str, str] = {}
    for method in methods:
        mid = method.get("id")
        if isinstance(mid, str):
            name = method.get("name")
            method_name[mid] = name if isinstance(name, str) else mid

    sub_set = {s for s in subscriptions if isinstance(s, str)}
    api_set = {p for p in api_providers if isinstance(p, str)}

    # Held subscriptions, in catalog order, with the surfaces each funds at $0.
    held_lines: list[str] = []
    for tier in tiers:
        provider = tier.get("provider")
        name = tier.get("tier")
        if not isinstance(provider, str) or not isinstance(name, str):
            continue
        if _tier_id(provider, name) not in sub_set:
            continue
        surfaces = [s for s in (tier.get("surface_funded") or []) if isinstance(s, str)]
        surface_str = (
            ", ".join(f"{method_name.get(s, s)} (`{s}`)" for s in surfaces) if surfaces else "—"
        )
        held_lines.append(
            f"- **{_display_label(name)}** ({provider}) funds at $0 marginal: {surface_str}."
        )

    # Enabled API providers, in catalog method order (deterministic). Prefer the
    # provider's per-token surface as the representative API method.
    api_method_by_provider: dict[str, dict[str, Any]] = {}
    provider_order: list[str] = []
    for method in methods:
        provider = method.get("provider")
        if not isinstance(provider, str) or method.get("billing") not in _API_BILLING:
            continue
        if provider not in api_method_by_provider:
            provider_order.append(provider)
            api_method_by_provider[provider] = method
        elif method.get("billing") == "per-token":
            api_method_by_provider[provider] = method

    api_lines: list[str] = []
    for provider in provider_order:
        if provider not in api_set:
            continue
        method = api_method_by_provider[provider]
        method_id = method.get("id")
        ref = f" (`{method_id}`)" if isinstance(method_id, str) else ""
        api_lines.append(
            f"- **{_provider_label(provider)}** — pay-per-token via your own API key{ref}."
        )

    budget = _DEFAULT_BUDGET_PRIORITY
    if isinstance(budget_priority, str) and budget_priority:
        budget = budget_priority

    # Consumption-headroom posture (effort axis): rendered only when it resolves
    # to `uncapped` (the behavior-changing case); `capped`/default emits nothing
    # so the prompt and the highest-volume default path stay unchanged. A leading
    # blank line keeps the block visually separated from the budget block above.
    headroom = _effective_consumption_headroom(consumption_headroom, sub_set, tiers)

    # FLAT-FUNDING GATE (tier axis): open only when a held subscription actually
    # funds a surface at $0 AND the user does not exhaust that budget. Both the
    # gate block and the consumption block are then rendered, and each is written
    # to reference the other's axis so the two can never read as contradictory.
    flat_funding = bool(held_lines) and headroom == "uncapped"
    flat_funding_line = "\n" + _flat_funding_block() + "\n" if flat_funding else ""
    consumption_line = (
        "\n" + _consumption_block(flat_funding=flat_funding) + "\n"
        if headroom == "uncapped"
        else ""
    )

    # No funding declared:
    #   - DEFAULT (balanced) budget -> None: the anon / free path is unchanged
    #     (the bundled template governs, exactly as before this lever existed),
    #     so we never shift the highest-volume default-toggle baseline.
    #   - an EXPLICIT non-default budget (Cost / Quality) -> still build, so the
    #     posture reaches the selector even for a signed-out user who actively
    #     changed the toggle. The funding sections then render "None declared."
    if not held_lines and not api_lines and budget == _DEFAULT_BUDGET_PRIORITY:
        return None

    juris = allowed_jurisdictions if allowed_jurisdictions else list(_BASELINE_JURISDICTIONS)

    held_block = "\n".join(held_lines) if held_lines else "- None declared."
    api_block = "\n".join(api_lines) if api_lines else "- None declared."

    # Access restriction (#445): the hard allowlist of models the user can run.
    # Only rendered when the user actually declared funding (held/api lines) —
    # an explicit-budget-only request with no funding declares no access, so it
    # keeps the frontier-first posture (nothing to restrict to).
    access_block = ""
    if held_lines or api_lines:
        accessible = accessible_model_ids(
            list(sub_set),
            list(api_set),
            allowed_jurisdictions=juris,
            platforms_allowed=platforms_allowed,
            platforms_excluded=platforms_excluded,
            catalog=cat,
        )
        names = _accessible_model_names(accessible, cat) if accessible else []
        access_block = "\n\n## Access restriction\n\n" + _access_restriction_block(names)

    # Operator platform allow/deny list (Step A00). Rendered only when declared,
    # so the default request keeps the leaner prompt; the HARD-filter semantics
    # and the RATIONALE disclosure requirement live in the block itself.
    plat_allowed = _str_list(platforms_allowed)
    plat_excluded = _str_list(platforms_excluded)
    platforms_block = ""
    if plat_allowed or plat_excluded:
        platforms_block = "\n\n## Allowed / excluded platforms\n\n" + _platforms_block(
            plat_allowed, plat_excluded
        )

    return f"""# User Context

This is the requesting user's declared funding, used by `<access-selection>`
to pick the cheapest PLATFORM that can run the recommended model. It is
generated per request from the user's saved settings and lists ONLY the
funding the user has declared.

## Active subscriptions

Held subscriptions and the access-method surfaces each funds at $0 marginal
cost (until that plan's usage budget is exhausted):

{held_block}

## Active API access

Providers the user can pay per-token for with their own API key (real dollars
per call). roadmodel stores only that the user has the key, never the key
itself:

{api_block}

## Platform preference order

When several access methods can run the chosen model, prefer them in this
order:

1. A held-subscription surface listed above that supports the chosen model
   ($0 marginal cost) — preferred on an exact quality tie.
2. An enabled API provider listed above that supports the chosen model
   (pay-per-token, real cash out).

The user has declared no other funding; do not assume a subscription or API
key that is not listed above.

## Budget priority and speed posture

{_budget_block(budget, flat_funding=flat_funding)}
{flat_funding_line}{consumption_line}
**Speed posture:** not a valued dimension unless the prompt states an explicit
latency requirement.

## Allowed jurisdictions

`{", ".join(juris)}`{platforms_block}{access_block}
"""


# --- Funded-platform honesty guard (#444) -----------------------------------
#
# The recommendation engine intermittently narrates funding the user never
# declared ("This runs on your claude.ai Max subscription") even though the
# per-user user-context says "None declared" and "do not assume". Prompt rules
# alone don't close this (same instruction-adherence class as #185-#190), so —
# like the deterministic THINKING=N/A override (#188) and the BACKUP guard
# (0.2.19) — we enforce it in code: when the picked platform is NOT
# subscription-funded for THIS user and the run-note claims subscription / $0
# funding, replace the run-note with deterministic honest text. Selection is
# never changed; only the false narration is.

# Phrasings that assert the user's funding covers the pick. \bfunded\b does
# not match "unfunded" (no word boundary inside it), so honest disclaimers
# survive; replacing an honest note that mentions e.g. "$0" with our own
# honest wording is harmless. The verb+"the" alternation catches the
# possessive-free variant seen in prod ("This uses the ChatGPT subscription
# via the Codex CLI") while "requires a subscription or API key" — the honest
# unfunded phrasing — stays unmatched (article "a", and no verb+"the").
_FUNDED_CLAIM_RE = re.compile(
    r"\byour\b[^.!\n]{0,60}\b(?:subscription|plan|pool)\b"
    r"|\bruns? on your\b"
    r"|\b(?:uses?|using|on|via|through|with|by)\s+the\s+[\w .+-]{0,30}\b(?:subscription|plan|pool)\b"
    r"|\bfunded\b"
    r"|\$0\b"
    r"|\bsubscription pool\b"
    r"|\bclaude\.ai max\b"
    r"|\bincluded (?:in|with) your\b",
    re.IGNORECASE,
)


class FundingGuard:
    """Deterministic post-check of a pick's run-note against declared funding.

    Built once per request from the SAME declared funding the user-context is
    rendered from, then applied to every pick (single and ladder). Pure text
    surgery: never changes the model, platform, or settings.
    """

    def __init__(
        self,
        subscriptions: list[str],
        api_providers: list[str],
        *,
        catalog: dict[str, Any] | None = None,
    ) -> None:
        cat = catalog if catalog is not None else load_catalog()
        tiers: Any = cat.get("subscription_tiers", []) or []
        methods: Any = cat.get("access_methods", []) or []
        sub_set = {s for s in subscriptions if isinstance(s, str)}
        self._api_set = {p for p in api_providers if isinstance(p, str)}

        # Access-method surfaces the held subscriptions fund at $0.
        self._sub_funded_ids: set[str] = set()
        for tier in tiers:
            provider = tier.get("provider")
            name = tier.get("tier")
            if not isinstance(provider, str) or not isinstance(name, str):
                continue
            if _tier_id(provider, name) not in sub_set:
                continue
            self._sub_funded_ids.update(
                s for s in (tier.get("surface_funded") or []) if isinstance(s, str)
            )

        # Platform-string lookup: the LLM emits catalog access-method NAMES
        # ("Claude Code", "Cursor", "xAI API"); index by lowercased name + id.
        self._methods: dict[str, dict[str, Any]] = {}
        for method in methods:
            mid = method.get("id")
            name = method.get("name")
            if isinstance(mid, str):
                self._methods[mid.strip().lower()] = method
            if isinstance(name, str):
                self._methods[name.strip().lower()] = method

    def _replacement(self, platform: str, method: dict[str, Any] | None) -> str:
        provider = method.get("provider") if method else None
        key_reachable = (
            method is not None
            and method.get("billing") in _API_BILLING
            and isinstance(provider, str)
            and provider in self._api_set
        )
        if key_reachable and isinstance(provider, str):
            return (
                f"Run this on {platform} pay-per-token with your "
                f"{_provider_label(provider)} API key — no subscription in your "
                f"Settings funds it at $0."
            )
        return (
            f"{platform} is not covered by any subscription or API access "
            f"declared in your Settings — running this pick requires access "
            f"you have not declared."
        )

    def sanitize(
        self,
        platform: str,
        rationale: str | None,
        rationale_sections: dict[str, str] | None,
    ) -> tuple[str | None, dict[str, str] | None]:
        """Return (rationale, rationale_sections) with false funded claims
        replaced. Fail-safe: any internal error returns the inputs unchanged —
        the guard must never turn a good recommendation into a failed one."""
        try:
            method = self._methods.get(platform.strip().lower())
            method_id = method.get("id") if method else None
            if isinstance(method_id, str) and method_id in self._sub_funded_ids:
                # A held subscription funds this surface: "your subscription"
                # claims are true — leave the engine's narration alone.
                return rationale, rationale_sections

            # The third rationale segment is EFFORT (a settings justification, no
            # funding narration) since 0.2.28; a stray funded claim there is a
            # hallucination we still scrub. `run` is accepted as the legacy key
            # for responses cached across the rename.
            effort_key = "effort" if (rationale_sections or {}).get("effort") else "run"
            if rationale_sections and rationale_sections.get(effort_key):
                effort = rationale_sections[effort_key]
                if not _FUNDED_CLAIM_RE.search(effort):
                    return rationale, rationale_sections
                honest = self._replacement(platform, method)
                sections = {**rationale_sections, effort_key: honest}
                # Rebuild the flat rationale in the same TASK/PICK/EFFORT shape so
                # the edge's unsplit fallback rendering stays consistent.
                task = sections.get("task", "")
                pick = sections.get("pick", "")
                label = "EFFORT" if effort_key == "effort" else "RUN"
                rebuilt = (
                    f"TASK: {task} PICK: {pick} {label}: {honest}" if task and pick else rationale
                )
                return rebuilt, sections

            # No structured sections: append a correction rather than attempt
            # surgical prose edits on free-form text.
            if rationale and _FUNDED_CLAIM_RE.search(rationale):
                honest = self._replacement(platform, method)
                return f"{rationale} Correction: {honest}", rationale_sections
            return rationale, rationale_sections
        except Exception:  # noqa: BLE001 - guard is best-effort, never fatal
            logger.warning("funding honesty guard failed (non-fatal)", exc_info=True)
            return rationale, rationale_sections


def funding_guard_from_request(context: dict[str, Any] | None) -> FundingGuard | None:
    """Build the per-request FundingGuard, or None when the guard must not run.

    Mirrors user_context_from_request's short-circuit exactly: the guard is
    active precisely when the per-user funding context was injected (i.e. the
    engine was TOLD the user's real funding). The anon / bundled-template path
    returns None so its narration — written against the bundled example
    funding by design — is never rewritten.
    """
    if not context:
        return None
    subscriptions = _str_list(context.get("subscriptions"))
    api_providers = _str_list(context.get("api_providers"))
    budget_raw = context.get("budget_priority")
    budget_priority = budget_raw if isinstance(budget_raw, str) else None
    budget_is_default = budget_priority is None or budget_priority == _DEFAULT_BUDGET_PRIORITY
    if not subscriptions and not api_providers and budget_is_default:
        return None
    try:
        return FundingGuard(subscriptions, api_providers)
    except Exception:  # noqa: BLE001 - guard is best-effort, never fatal
        logger.warning("funding guard build failed (non-fatal)", exc_info=True)
        return None


# --- Access-restriction guard (#445) ----------------------------------------
#
# Hard backstop for the user-context allowlist: the bias tells the engine to
# recommend only accessible models, but adherence isn't guaranteed (the #444
# lesson). After a pick is parsed, if its MODEL (or BACKUP) is outside the
# accessible set, substitute the best accessible model deterministically and
# rewrite the rationale — so an inaccessible model can NEVER reach the user.
# No-op when the accessible set is empty (nothing to substitute to) — the
# user-context already instructs the engine to flag that case in prose.

# Letter tier -> capability points, summed across categories for a coarse
# quality score used only to rank substitutes deterministically.
_TIER_POINTS: dict[str, int] = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


class AccessGuard:
    """Deterministic enforcement of the accessible-model allowlist on a pick.

    Built per request from the user's declared access; applied to every pick
    (single + ladder). Substitutes an inaccessible MODEL/BACKUP with the best
    accessible one for the rung and rewrites the rationale honestly. Pure over
    the catalog; never raises (fails open to the engine's pick).
    """

    def __init__(
        self,
        accessible_ids: set[str],
        api_providers: list[str],
        funded_surface_ids: set[str],
        *,
        platforms_allowed: list[str] | None = None,
        platforms_excluded: list[str] | None = None,
        catalog: dict[str, Any] | None = None,
    ) -> None:
        cat = catalog if catalog is not None else load_catalog()
        self._accessible_ids = set(accessible_ids)
        # Operator platform allow/deny list (Step A00). The accessible SET was
        # already filtered by it upstream; this second application governs which
        # surface a substituted pick is NAMED with, so the guard can never label
        # a model with a platform the operator declared they do not use.
        allow_platforms = _platform_id_set(platforms_allowed)
        deny_platforms = _platform_id_set(platforms_excluded)
        self._allow_platforms = allow_platforms
        self._deny_platforms = deny_platforms
        # Access-method NAME (as the engine emits it) -> id, so a PLATFORM string
        # can be matched against the operator's id-based allow/deny list.
        self._method_id_of: dict[str, str] = {}
        # Models whose platform label came from a PERMITTED surface — the only
        # relabel targets when the engine names an excluded platform.
        self._permitted_platform_of: dict[str, str] = {}
        self._api_set = {p for p in api_providers if isinstance(p, str)}
        self._funded_surface_ids = set(funded_surface_ids)
        models: Any = cat.get("models", []) or []
        methods: Any = cat.get("access_methods", []) or []

        # name/id -> id, and per-model metadata for ranking + display.
        self._id_of: dict[str, str] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        for model in models:
            mid = model.get("id")
            if not isinstance(mid, str):
                continue
            name = model.get("name") if isinstance(model.get("name"), str) else mid
            self._id_of[mid.strip().lower()] = mid
            self._id_of[str(name).strip().lower()] = mid
            try:
                out_price = float(model.get("output_price_per_1m") or 0.0)
            except (TypeError, ValueError):
                out_price = 0.0
            tiers = model.get("tiers") if isinstance(model.get("tiers"), dict) else {}
            quality = sum(_TIER_POINTS.get(str(v).strip().upper(), 0) for v in tiers.values())
            self._meta[mid] = {"name": name, "out_price": out_price, "quality": quality}

        # model id -> a user-usable access-method display name. A $0-funded
        # subscription surface is PREFERRED over a pay-per-token API surface (the
        # "your cost to you" ordering also documented in the user-context Platform
        # preference), so e.g. Claude Haiku shows "Claude Code" ($0 via Max), not
        # "Anthropic API". Was first-usable-in-catalog-order, which could label a
        # $0-funded model with a paid API surface.
        self._platform_of: dict[str, str] = {}
        _funded_platform_of: dict[str, str] = {}
        _api_platform_of: dict[str, str] = {}
        # Same two maps built from the methods the platform filter DROPPED, used
        # only as a last-resort label so a filtered-out surface never leaves an
        # accessible model with no platform at all (fail-safe, mirroring
        # accessible_model_ids' fallback).
        _funded_dropped_of: dict[str, str] = {}
        _api_dropped_of: dict[str, str] = {}
        self._maker_of: dict[str, str] = {}
        # Models reachable at $0 via a funded SUBSCRIPTION surface — their
        # effective cost to the user is $0, used to prefer them for the Cost pick
        # (a $0 Claude Haiku beats a $0.003 GPT Nano on "your cost to you").
        self._funded_model_ids: set[str] = set()
        # All provider makers that support each model, so the MAKER can be
        # resolved aggregator-aware below (a first pass; resolution follows).
        providers_by_model: dict[str, set[str]] = {}
        for method in methods:
            provider = method.get("provider")
            mid = method.get("id")
            name = method.get("name")
            display = name if isinstance(name, str) else str(mid)
            if isinstance(mid, str):
                self._method_id_of[mid.strip().lower()] = mid
                if isinstance(name, str) and name.strip():
                    self._method_id_of[name.strip().lower()] = mid
            api_usable = method.get("billing") in _API_BILLING and provider in self._api_set
            funded_sub = isinstance(mid, str) and mid in self._funded_surface_ids
            permitted = _method_permitted(mid, allow_platforms, deny_platforms)
            for supported in method.get("supports_models") or []:
                if not isinstance(supported, str):
                    continue
                if isinstance(provider, str):
                    # Maker resolution is deliberately NOT platform-filtered: a
                    # model's maker is a property of the model, not of which
                    # surfaces this operator happens to use.
                    providers_by_model.setdefault(supported, set()).add(provider)
                if funded_sub:
                    # A $0 surface the operator excluded is not operable, so it
                    # must not make the model count as "free to you" for the
                    # Cost ranking either.
                    if permitted:
                        self._funded_model_ids.add(supported)
                        _funded_platform_of.setdefault(supported, display)
                    else:
                        _funded_dropped_of.setdefault(supported, display)
                if api_usable:
                    if permitted:
                        _api_platform_of.setdefault(supported, display)
                    else:
                        _api_dropped_of.setdefault(supported, display)
        # Funded ($0) surface first, then a declared pay-per-token API surface;
        # a platform-filtered-out surface only as a last resort (see above).
        for mid_ in {*_funded_platform_of, *_api_platform_of}:
            self._permitted_platform_of[mid_] = (
                _funded_platform_of.get(mid_) or _api_platform_of[mid_]
            )
        for mid_ in {
            *_funded_platform_of,
            *_api_platform_of,
            *_funded_dropped_of,
            *_api_dropped_of,
        }:
            self._platform_of[mid_] = (
                self._permitted_platform_of.get(mid_)
                or _funded_dropped_of.get(mid_)
                or _api_dropped_of[mid_]
            )
        # Resolve each model's MAKER excluding pool aggregators (Cursor), mirroring
        # roadmodel.cost.model_provider so THIS guard's cross-provider backup check
        # agrees with the package's. A model reachable via Cursor's pool AND its
        # own provider resolves to its real maker; one reachable ONLY via an
        # aggregator keeps the aggregator. Fixes the aggregator-drift bug: taking
        # the FIRST method's provider resolved GPT-5.4 Nano (via Cursor's pool) to
        # "cursor" instead of "openai", so a same-maker OpenAI backup passed the
        # different-maker check (observed in prod: GPT-5.4 Nano + GPT-5 Mini).
        for supported, provs in providers_by_model.items():
            first_party = provs - _AGGREGATOR_PROVIDERS
            if len(first_party) == 1:
                self._maker_of[supported] = next(iter(first_party))
            elif not first_party and len(provs) == 1:
                self._maker_of[supported] = next(iter(provs))
            # Ambiguous (multiple first-party makers) -> unknown, matching
            # model_provider — the different-maker guard then fails safe.

    def _resolve_id(self, model_ref: str | None) -> str | None:
        if not model_ref:
            return None
        key = model_ref.strip().lower()
        mid = self._id_of.get(key)
        if mid is not None:
            return mid
        # Resolve miss: the engine sometimes prepends the maker/product line
        # ("Claude Fable 5" for catalog "Fable 5"). Strip a leading vendor word
        # and retry so an accessible pick isn't misread as inaccessible.
        for prefix in _VENDOR_NAME_PREFIXES:
            if key.startswith(prefix):
                stripped = self._id_of.get(key[len(prefix) :].strip())
                if stripped is not None:
                    return stripped
        return None

    def is_accessible(self, model_ref: str | None) -> bool:
        mid = self._resolve_id(model_ref)
        return mid is not None and mid in self._accessible_ids

    def platform_for(self, model_ref: str | None) -> str | None:
        """The user-usable access-method DISPLAY NAME for a model (the declared
        API per-token surface, else a funded subscription surface), or None when
        the model isn't in the catalog / has no usable surface. Used to give the
        Step 7 backup its own funded platform, mirroring the primary pick."""
        mid = self._resolve_id(model_ref)
        return self._platform_of.get(mid) if mid is not None else None

    def _rank_key(self, priority: str, model_id: str) -> tuple[Any, ...]:
        meta = self._meta.get(model_id, {})
        quality = int(meta.get("quality", 0))
        price = float(meta.get("out_price", 0.0))
        prio = priority.strip().lower()
        if prio == "cheap":
            # Prefer a $0-funded model (effective cost $0 to the user) over a
            # cheap pay-per-token one, THEN cheapest raw price (smallest adequate),
            # higher quality, id — min() key. Before this, a $0-funded Claude Haiku
            # (raw ~$4/M) lost to a $0.003 GPT Nano on raw price, so the Cost
            # substitute charged real cash when a funded model was free (dogfood).
            funded_rank = 0 if model_id in self._funded_model_ids else 1
            return (funded_rank, price, -quality, model_id)
        if prio == "best":
            # Highest quality, then pricier (proxy capability), then id — max().
            return (quality, price, _neg_str(model_id))
        # balanced: best value = quality per dollar, then quality, then id — max().
        value = quality / price if price > 0 else float(quality)
        return (value, quality, _neg_str(model_id))

    def _best_substitute(self, priority: str, *, exclude_maker: str | None = None) -> str | None:
        candidates = [
            mid
            for mid in self._accessible_ids
            if mid in self._meta
            and (exclude_maker is None or self._maker_of.get(mid) != exclude_maker)
        ]
        if not candidates:
            return None
        prio = priority.strip().lower()
        if prio == "cheap":
            return min(candidates, key=lambda m: self._rank_key(prio, m))
        return max(candidates, key=lambda m: self._rank_key(prio, m))

    def enforce(self, result: dict[str, Any], priority: str) -> bool:
        """Substitute an inaccessible MODEL/BACKUP in ``result`` (mutated in
        place). Returns True when the primary MODEL was substituted."""
        try:
            changed = False
            if not self.is_accessible(result.get("model")):
                sub_id = self._best_substitute(priority)
                # Never "substitute" a model with itself: if the best accessible
                # substitute IS the model the engine named (a name mismatch the
                # resolver didn't catch, e.g. an unregistered prefix), keep the
                # pick rather than emit "<X> is strongest; <X> was outside access."
                original_ref = str(result.get("model") or "").strip().lower()
                sub_name = (
                    str(self._meta.get(sub_id, {}).get("name", "")).strip().lower()
                    if sub_id
                    else ""
                )
                same_model = bool(sub_name) and (
                    sub_name in original_ref or original_ref in sub_name
                )
                if sub_id is not None and not same_model:
                    self._apply_primary_substitution(result, sub_id)
                    changed = True
            # Backup must also be accessible AND a different maker than the
            # (possibly new) primary; substitute or drop otherwise.
            backup = result.get("backup")
            if backup:
                primary_id = self._resolve_id(result.get("model"))
                primary_maker = self._maker_of.get(primary_id) if primary_id else None
                if not self.is_accessible(backup) or (
                    primary_maker is not None
                    and self._maker_of.get(self._resolve_id(backup) or "") == primary_maker
                ):
                    sub_backup = self._best_substitute(priority, exclude_maker=primary_maker)
                    result["backup"] = self._meta[sub_backup]["name"] if sub_backup else None
            # Platform allow/deny list (Step A00): the model can be perfectly
            # accessible and still be routed through a surface the operator
            # declared they do not use — prompt bias alone doesn't stop that
            # (the #444 lesson), so relabel it deterministically here.
            self._enforce_platform(result)
            return changed
        except Exception:  # noqa: BLE001 - guard is best-effort, never fatal
            logger.warning("access guard failed (non-fatal)", exc_info=True)
            return False

    def platform_permitted(self, platform: str | None) -> bool:
        """Whether a PLATFORM string survives the operator's allow/deny list.

        Resolves the engine-emitted display name back to its catalog id first.
        An unresolvable platform is permitted only in deny-list-only mode — the
        same fail-open rule ``_method_permitted`` applies to a nameless method.
        """
        if not self._allow_platforms and not self._deny_platforms:
            return True
        key = (platform or "").strip().lower()
        return _method_permitted(
            self._method_id_of.get(key, key), self._allow_platforms, self._deny_platforms
        )

    def _enforce_platform(self, result: dict[str, Any]) -> None:
        """Relabel a pick routed through an excluded platform onto a permitted
        surface that reaches the SAME model, disclosing the swap in the rationale.

        No-op when nothing is declared, when the platform is already permitted,
        or when no permitted surface reaches the model (the user-context prose
        already instructs the engine to say so plainly in that case — silently
        re-admitting the excluded surface would be worse)."""
        platform = result.get("platform")
        if self.platform_permitted(platform if isinstance(platform, str) else None):
            return
        model_id = self._resolve_id(result.get("model"))
        replacement = self._permitted_platform_of.get(model_id) if model_id else None
        if not replacement or replacement == platform:
            return
        result["platform"] = replacement
        result["platform_guard"] = {
            "action": "relabelled",
            "original": platform,
            "substitute": replacement,
        }
        disclosure = (
            f"{platform} is not in the operator's declared platform list, so this "
            f"runs on {replacement} instead."
        )
        sections = result.get("rationale_sections")
        if isinstance(sections, dict):
            key = "effort" if sections.get("effort") else "run"
            existing = sections.get(key) or ""
            result["rationale_sections"] = {
                **sections,
                key: f"{existing} {disclosure}".strip(),
            }
        rationale = result.get("rationale")
        if isinstance(rationale, str) and rationale:
            result["rationale"] = f"{rationale} {disclosure}"

    def _apply_primary_substitution(self, result: dict[str, Any], sub_id: str) -> None:
        name = str(self._meta[sub_id]["name"])
        platform = self._platform_of.get(sub_id, result.get("platform", ""))
        original = result.get("model", "the engine's pick")
        result["model"] = name
        result["platform"] = platform
        # Rewrite rationale to a deterministic, honest note. Keep the engine's
        # task framing when structured; replace pick/run.
        sections = result.get("rationale_sections")
        task = ""
        if isinstance(sections, dict) and isinstance(sections.get("task"), str):
            task = sections["task"]
        pick = (
            f"{name} is the strongest model your declared access can run for this "
            f"task; {original} was outside your access and was not recommendable."
        )
        run = (
            f"Run this on {platform} pay-per-token with your own API key — it is "
            f"the accessible substitute for {original}."
        )
        result["rationale_sections"] = {
            "task": task or "Matched to the models your declared access can run.",
            "pick": pick,
            "run": run,
        }
        result["rationale"] = (
            f"TASK: {task or 'Matched to your declared access.'} PICK: {pick} RUN: {run}"
        )
        result["access_guard"] = {"action": "substituted", "original": original, "substitute": name}


def _neg_str(value: str) -> tuple[int, ...]:
    """A key that inverts string ordering for use inside a max() tuple, so a
    LOWER id wins ties (stable, deterministic) even while maximizing."""
    return tuple(-ord(c) for c in value)


def access_guard_from_request(context: dict[str, Any] | None) -> AccessGuard | None:
    """Build the per-request AccessGuard, or None when no restriction applies.

    Active exactly when the user declared funding (api providers or held
    subscriptions). Anon / no-funding -> None (frontier-first posture, no
    restriction). Never raises.
    """
    if not context:
        return None
    subscriptions = _str_list(context.get("subscriptions"))
    api_providers = _str_list(context.get("api_providers"))
    if not subscriptions and not api_providers:
        return None
    try:
        cat = load_catalog()
        allowed = resolve_allowed_jurisdictions(context)
        plat_allowed, plat_excluded = resolve_platform_filters(context)
        accessible = accessible_model_ids(
            subscriptions,
            api_providers,
            allowed_jurisdictions=allowed,
            platforms_allowed=plat_allowed,
            platforms_excluded=plat_excluded,
            catalog=cat,
        )
        if accessible is None:
            return None
        tiers: Any = cat.get("subscription_tiers", []) or []
        funded = _funded_surface_ids(tiers, set(subscriptions))
        return AccessGuard(
            accessible,
            api_providers,
            funded,
            platforms_allowed=plat_allowed,
            platforms_excluded=plat_excluded,
            catalog=cat,
        )
    except Exception:  # noqa: BLE001 - guard is best-effort, never fatal
        logger.warning("access guard build failed (non-fatal)", exc_info=True)
        return None


def resolve_allowed_jurisdictions(context: dict[str, Any] | None) -> list[str]:
    """The user's permitted jurisdictions for a request — the forwarded
    ``allowed_jurisdictions`` list, or the documented baseline when absent. This
    is the SAME set the selector uses for Step 0b, so the package's cross-provider
    backup substitution filters candidates consistently with the primary pick."""
    parsed = _str_list((context or {}).get("allowed_jurisdictions"))
    return parsed or list(_BASELINE_JURISDICTIONS)


def user_context_from_request(context: dict[str, Any] | None) -> str | None:
    """Build the per-user user-context from a RecommendRequest.context dict.

    Short-circuits to None when no funding is declared (the anon / free path),
    so the bundled template is used and behavior is unchanged. Null-safe: every
    field is read defensively (the context dict is untyped).
    """
    if not context:
        return None
    subscriptions = _str_list(context.get("subscriptions"))
    api_providers = _str_list(context.get("api_providers"))

    budget_raw = context.get("budget_priority")
    budget_priority = budget_raw if isinstance(budget_raw, str) else None
    headroom_raw = context.get("consumption_headroom")
    consumption_headroom = headroom_raw if isinstance(headroom_raw, str) else None
    allowed_jurisdictions = _str_list(context.get("allowed_jurisdictions")) or None
    # Operator platform allow/deny list (Step A00). Same defensive read as
    # allowed_jurisdictions, and the same "empty list means UNSET" semantics —
    # an absent allowlist must never be read as "allow nothing".
    platforms_allowed, platforms_excluded = resolve_platform_filters(context)

    # No funding declared -> short-circuit to the bundled template (free path
    # unchanged) UNLESS the user explicitly chose a non-default budget priority:
    # the Cost / Quality posture must still reach the selector signed-out. A
    # default (or absent) budget with no funding stays on the bundled template,
    # so the highest-volume default path never pays a catalog build. Mirrors the
    # same guard in build_user_context.
    budget_is_default = budget_priority is None or budget_priority == _DEFAULT_BUDGET_PRIORITY
    if not subscriptions and not api_providers and budget_is_default:
        return None

    try:
        return build_user_context(
            subscriptions,
            api_providers,
            budget_priority=budget_priority,
            consumption_headroom=consumption_headroom,
            allowed_jurisdictions=allowed_jurisdictions,
            platforms_allowed=platforms_allowed or None,
            platforms_excluded=platforms_excluded or None,
        )
    except Exception:  # noqa: BLE001 - funding context is best-effort, never fatal
        # A catalog read/parse failure must not turn a good request into a 500;
        # degrade to the bundled template (the pre-T2b behavior).
        logger.warning("per-user funding context build failed (non-fatal)", exc_info=True)
        return None
