# src/roadmodel/cost.py
"""Pure session-cost estimator over the bundled catalog.

Reads `roadmodel/data/catalog.json` via `importlib.resources`, resolves a
`(model, platform)` pair against the catalog's per-token prices and
access-method `billing` field, applies the Cursor Max Mode 2x-input rule
when `max_mode=True` and the chosen access method exposes Max Mode, and
decorates the result with a `funding_source` label resolved against the
user's `user-context.md`.

No network, no provider calls; the module is pure. All paths can be
overridden by env vars (`ROADMODEL_CATALOG_PATH`, `ROADMODEL_USER_CONTEXT`)
so tests can drive every billing branch off fixture catalogs.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Final

from roadmodel import user_context
from roadmodel.errors import (
    AlternativeRejectedError,
    BundledDocNotFoundError,
    UserContextNotFoundError,
)

BUNDLED_CATALOG_PATH: Traversable = resources.files("roadmodel.data") / "catalog.json"

_FUNDING_PRIORITY: Final[dict[str, int]] = {
    # A FUNDED local method is $0 with no usage pool behind it at all — it
    # ranks with the subscription tier (<access-selection> Step C tier 1).
    "local": 0,
    "subscription-included": 0,
    "subscription-pool": 1,
    "subscription-or-key": 2,
    "per-token": 3,
}

# Funding labels for `billing="local"` access methods (Phase 4.10). `local` is
# the funded case — the user-context declares the runtime present AND lists the
# model as pulled; `unfunded-local` means the hardware / pull is not declared,
# and <access-selection> Step B DROPS such a method (it is not money the user
# might spend), so the comparison panel omits it rather than pricing it.
FUNDING_LOCAL: Final = "local"
FUNDING_UNFUNDED_LOCAL: Final = "unfunded-local"
LOCAL_COST_LABEL: Final = "$0 — local hardware"

_FAST_SUFFIX_RE: Final = re.compile(r"\s+Fast\s*$", re.IGNORECASE)
# A trailing parenthetical on a tier name — the catalog's "($100)" price tag
# or an operator's own "(5x)" — is not part of the tier's identity; the
# monthly price is compared separately.
_TIER_PAREN_RE: Final = re.compile(r"\s*\([^()]*\)\s*$")
_TABLE_ROW_RE: Final = re.compile(r"^\s*\|(.+)\|\s*$")


@dataclass(frozen=True)
class SessionCostEstimate:
    model_id: str
    model_name: str
    platform_id: str
    platform_name: str
    input_tokens: int
    output_tokens: int
    max_mode: bool
    input_usd: float
    output_usd: float
    total_usd: float
    funding_source: str
    subscription_label: str | None
    notes: list[str] = field(default_factory=list)


def estimate_session_cost(
    model_id: str,
    platform_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    max_mode: bool = False,
    user_context_text: str | None = None,
) -> SessionCostEstimate:
    """Estimate a single (model, platform) session cost.

    ``user_context_text`` overrides the on-disk user-context (env override or
    default path) so a caller that already resolved the operator's file — the
    CLI's ``--user-context``, the service's per-request context — prices
    funding against the SAME text the recommendation was made from.
    """
    catalog = _load_catalog()
    _reject_fast_variant(model_id, catalog)
    model = _resolve_model(model_id, catalog)
    method = _resolve_method(platform_id, catalog)

    notes: list[str] = []
    input_multiplier = 1.0
    if max_mode:
        if method.get("exposes_max_mode") == "yes":
            input_multiplier = 2.0
            notes.append("Max Mode 2x input pricing applied")
        else:
            notes.append(
                f"Max Mode is a Cursor-surface dial; no-op on {method['name']} "
                "(access method does not expose Max Mode)."
            )

    if user_context_text is None:
        user_context_text = _load_user_context_text()
    funding_source, active_tier = _resolve_funding(
        _with_model(method, str(model["id"])), catalog, user_context_text
    )
    subscription_label = _format_subscription_label(active_tier) if active_tier else None

    if funding_source in {FUNDING_LOCAL, FUNDING_UNFUNDED_LOCAL}:
        # Self-hosted weights: the model's hosted per-token price does not
        # apply, so there is NO per-token estimate — only the fixed label. An
        # unfunded local platform is additionally flagged as not reachable.
        input_usd = output_usd = total_usd = 0.0
        if funding_source == FUNDING_LOCAL:
            notes.append(f"{LOCAL_COST_LABEL} (no per-token estimate)")
        else:
            notes.append(
                "Not reachable: user-context does not declare the Ollama runtime "
                f"and/or {model['id']} among the pulled models (dropped by "
                "<access-selection> Step B)."
            )
    else:
        input_price = float(model["input_price_per_1m"])
        output_price = float(model["output_price_per_1m"])
        input_usd = input_tokens * input_price / 1_000_000.0 * input_multiplier
        output_usd = output_tokens * output_price / 1_000_000.0
        total_usd = input_usd + output_usd

    return SessionCostEstimate(
        model_id=str(model["id"]),
        model_name=str(model["name"]),
        platform_id=str(method["id"]),
        platform_name=str(method["name"]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        max_mode=max_mode,
        input_usd=input_usd,
        output_usd=output_usd,
        total_usd=total_usd,
        funding_source=funding_source,
        subscription_label=subscription_label,
        notes=notes,
    )


def compare_alternatives(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    alternatives: list[str] | None = None,
    max_mode: bool = False,
    user_context_text: str | None = None,
) -> list[SessionCostEstimate]:
    """Compare a model across access methods, cheapest-first."""
    catalog = _load_catalog()
    _reject_fast_variant(model_id, catalog)
    model = _resolve_model(model_id, catalog)
    resolved_model_id = str(model["id"])

    if alternatives is None:
        estimates = _default_alternative_estimates(
            resolved_model_id,
            catalog,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            max_mode=max_mode,
            user_context_text=user_context_text,
        )
        estimates.sort(
            key=lambda est: (est.total_usd, _FUNDING_PRIORITY.get(est.funding_source, 99))
        )
        return estimates

    return [
        estimate_session_cost(
            resolved_model_id,
            platform_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            max_mode=max_mode,
            user_context_text=user_context_text,
        )
        for platform_id in alternatives
    ]


def _default_alternative_estimates(
    model_id: str,
    catalog: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
    max_mode: bool = False,
    user_context_text: str | None = None,
) -> list[SessionCostEstimate]:
    if user_context_text is None:
        user_context_text = _load_user_context_text()
    candidates: list[tuple[dict[str, Any], str]] = []
    for method in catalog.get("access_methods", []):
        if model_id not in method.get("supports_models", []):
            continue
        funding_source, _ = _resolve_funding(
            _with_model(method, model_id), catalog, user_context_text
        )
        if funding_source == FUNDING_UNFUNDED_LOCAL:
            # Step B drops an undeclared local method outright; it is not a
            # platform the user could pay to reach, so it gets no row.
            continue
        candidates.append((method, funding_source))
    candidates.sort(
        key=lambda entry: (
            _FUNDING_PRIORITY.get(entry[1], 99),
            str(entry[0]["id"]),
        )
    )
    top_three = candidates[:3]
    return [
        estimate_session_cost(
            model_id,
            str(method["id"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            max_mode=max_mode,
            user_context_text=user_context_text,
        )
        for method, _ in top_three
    ]


def compare_alternatives_funding_rank(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    max_mode: bool = False,
    user_context_text: str | None = None,
) -> list[SessionCostEstimate]:
    """Return up to three estimates for *model_id* in funding-priority order."""
    catalog = _load_catalog()
    _reject_fast_variant(model_id, catalog)
    model = _resolve_model(model_id, catalog)
    resolved_model_id = str(model["id"])
    return _default_alternative_estimates(
        resolved_model_id,
        catalog,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        max_mode=max_mode,
        user_context_text=user_context_text,
    )


def _load_catalog() -> dict[str, Any]:
    override = os.environ.get("ROADMODEL_CATALOG_PATH")
    try:
        if override:
            text = Path(override).expanduser().read_text(encoding="utf-8")
        else:
            text = BUNDLED_CATALOG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError("catalog.json") from exc
    parsed: object = json.loads(text)
    if not isinstance(parsed, dict):
        raise BundledDocNotFoundError("catalog.json")
    return parsed


def _load_user_context_text() -> str:
    override = os.environ.get("ROADMODEL_USER_CONTEXT")
    if override:
        path = Path(override).expanduser()
    else:
        path = user_context.resolve(cli_path=None)
    try:
        return user_context.read(path)
    except UserContextNotFoundError:
        return ""


def _resolve_model(model_id: str, catalog: dict[str, Any]) -> dict[str, Any]:
    models = catalog.get("models", [])
    for entry in models:
        if entry["id"] == model_id or entry["name"] == model_id:
            return _as_dict(entry)
    raise ValueError(
        f"Unknown model_id: {model_id!r}. "
        f"Catalog has {len(models)} models; pass either the model id or name."
    )


def _resolve_method(platform_id: str, catalog: dict[str, Any]) -> dict[str, Any]:
    methods = catalog.get("access_methods", [])
    for entry in methods:
        if entry["id"] == platform_id or entry["name"] == platform_id:
            return _as_dict(entry)
    raise ValueError(
        f"Unknown platform_id: {platform_id!r}. "
        f"Catalog has {len(methods)} access methods; pass either the id or name."
    )


def canonical_model_name(model_ref: str) -> str:
    """Resolve a model id-or-name to its catalog display ``name``; return the
    input unchanged on any catalog miss (never raises).

    The recommender LLM emits the model freely as either the catalog id/slug
    or the display name, which made the response header (raw) disagree with the
    cost/comparison table (catalog name) and risked silently dropping the cost
    panel on an unrecognized label (#174). Callers canonicalize once so every
    downstream consumer references one consistent name.
    """
    try:
        return str(_resolve_model(model_ref, _load_catalog())["name"])
    except (ValueError, BundledDocNotFoundError):
        return model_ref


def canonical_platform_name(platform_ref: str) -> str:
    """Resolve an access-method id-or-name to its catalog display ``name``;
    return the input unchanged on any catalog miss (never raises) (#174)."""
    try:
        return str(_resolve_method(platform_ref, _load_catalog())["name"])
    except (ValueError, BundledDocNotFoundError):
        return platform_ref


# Pricing-tier buckets by OUTPUT price per 1M tokens, mirroring
# docs/model-tier-cost-scale.md: Low < $10, Medium $10–14.99, High $15–24.99,
# Very High >= $25. Rank is an integer so tiers compare directly (higher rank =
# pricier): low=0, medium=1, high=2, very-high=3. Used by the tier-ladder guard
# to check the Cost/Balanced/Quality picks occupy distinct, decreasing tiers.
_PRICING_TIER_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "very-high": 3}


def pricing_tier(model_ref: str) -> str | None:
    """Resolve a model id-or-name to its pricing tier
    (``low`` / ``medium`` / ``high`` / ``very-high``) by bucketing its catalog
    output price, per docs/model-tier-cost-scale.md. Returns ``None`` on any
    catalog miss or missing price (never raises), so the ladder guard degrades
    to "tier unknown" rather than failing a recommendation."""
    try:
        model = _resolve_model(model_ref, _load_catalog())
        output_price = float(model["output_price_per_1m"])
    except (ValueError, BundledDocNotFoundError, KeyError, TypeError):
        return None
    if output_price < 10.0:
        return "low"
    if output_price < 15.0:
        return "medium"
    if output_price < 25.0:
        return "high"
    return "very-high"


def pricing_tier_rank(tier: str | None) -> int | None:
    """Map a pricing-tier name to its integer rank (higher = pricier), or
    ``None`` when the tier is unknown."""
    if tier is None:
        return None
    return _PRICING_TIER_RANK.get(tier)


# Pool aggregators — access-method providers that RESELL or RE-HOST other
# companies' models rather than making them: Cursor's subscription pool,
# OpenRouter's per-token aggregator, and the local Ollama runtime (which serves
# open weights whose maker is OpenAI / DeepSeek / z.ai / …). They must NOT be
# treated as a model's "maker" when resolving provider for the cross-provider
# backup guard: Opus 4.8 is reachable via Cursor and OpenRouter, but its maker
# is Anthropic, and an Anthropic outage is what a backup must survive; gpt-oss
# is reachable via Groq, OpenRouter and Ollama, and its maker is Groq's method
# (the pinned host that defines its price + access). A model reachable ONLY
# through an aggregator (e.g. Cursor's own Composer models) falls back to the
# aggregator provider, since in that case the aggregator IS the maker — exactly
# as a model reachable only via OpenRouter would resolve to `openrouter`.
_AGGREGATOR_PROVIDERS: frozenset[str] = frozenset({"cursor", "openrouter", "ollama"})
# When a model is reachable through SEVERAL aggregators and no first-party
# method (today: Kimi K3 / K2.7 Code and Muse Spark, which have no catalogued
# maker method), resolve to the first of these so the answer stays the one the
# pre-4.10 catalog gave (`cursor`) and the same-family backup guard keeps
# catching Kimi-vs-Kimi. A per-model `maker` attribute would be the real fix.
_AGGREGATOR_FALLBACK_ORDER: tuple[str, ...] = ("cursor", "openrouter", "ollama")

# Providers whose access method is a LOCAL runtime (billing `local`). A model
# whose only reachable platform is one of these is never a usable backup
# unless the user has pulled it, which the catalog cannot know — so the
# cross-provider backup substitution skips such candidates.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})


def model_provider(model_ref: str) -> str | None:
    """Resolve a model id-or-name to its MAKER (the company that produces it):
    ``anthropic`` / ``openai`` / ``google`` / ``xai`` / ``deepseek`` / ``mistral``
    / ``zai`` / ``groq`` / ``cursor`` …

    The maker is the ``provider`` of a first-party access method that supports the
    model, EXCLUDING pool aggregators (``_AGGREGATOR_PROVIDERS``) — so a model
    reachable via both its provider's own API and Cursor's pool resolves to its
    real maker, not Cursor. A model reachable only through an aggregator resolves
    to that aggregator (it is the maker, e.g. Cursor's Composer). Returns ``None``
    on a catalog miss or an ambiguous/absent mapping (never raises), so the
    cross-provider backup guard degrades to "can't prove same maker → allow"
    rather than dropping a valid backup.
    """
    try:
        catalog = _load_catalog()
        model_id = str(_resolve_model(model_ref, catalog)["id"])
    except (ValueError, BundledDocNotFoundError, KeyError, TypeError):
        return None
    methods = catalog.get("access_methods", [])
    if not isinstance(methods, list):
        return None
    supporting: set[str] = set()
    for method in methods:
        if not isinstance(method, dict):
            continue
        if model_id in method.get("supports_models", []):
            provider = method.get("provider")
            if isinstance(provider, str) and provider:
                supporting.add(provider)
    first_party = supporting - _AGGREGATOR_PROVIDERS
    if len(first_party) == 1:
        return next(iter(first_party))
    if not first_party and supporting:
        # Reachable only through aggregators → the (preferred) aggregator is
        # the maker (Cursor's own Composer; see _AGGREGATOR_FALLBACK_ORDER).
        for aggregator in _AGGREGATOR_FALLBACK_ORDER:
            if aggregator in supporting:
                return aggregator
        return next(iter(sorted(supporting)))
    # No supporting method, or an ambiguous multi-provider mapping (should not
    # happen for a real maker) → unknown.
    return None


def same_provider(model_a: str, model_b: str) -> bool:
    """True iff two models resolve to the SAME known maker. Unknown on either
    side → False (we never assert a same-maker collision we can't prove), so a
    caller using this to REJECT a backup fails safe (keeps the backup)."""
    provider_a = model_provider(model_a)
    provider_b = model_provider(model_b)
    return provider_a is not None and provider_a == provider_b


def model_id_of(model_ref: str) -> str | None:
    """Resolve a model id-or-name to its catalog ``id`` (the stable slug), or
    ``None`` on a catalog miss (never raises). The runtime availability list
    (Step 0a) is keyed by id, so callers checking whether a model is benched
    canonicalize a free-form ref to its id first."""
    try:
        return str(_resolve_model(model_ref, _load_catalog())["id"])
    except (ValueError, BundledDocNotFoundError, KeyError):
        return None


def model_jurisdiction(model_ref: str) -> str | None:
    """Resolve a model id-or-name to its catalog ``jurisdiction`` (lowercased),
    or ``None`` on a catalog miss / missing field (never raises).

    Mirrors the fail-safe stance of :func:`model_provider`: a caller using this
    to REJECT a region-blocked backup should keep the backup when this returns
    ``None`` (we never assert a jurisdiction violation we can't prove)."""
    try:
        model = _resolve_model(model_ref, _load_catalog())
    except (ValueError, BundledDocNotFoundError):
        return None
    juris = str(model.get("jurisdiction", "")).strip().lower()
    return juris or None


def suggest_cross_provider_backup(
    primary_model: str,
    *,
    allowed_jurisdictions: list[str],
    unavailable_models: list[str] | None = None,
) -> str | None:
    """Deterministically pick the best cross-provider fallback for ``primary_model``
    — the substitution behind the Step 7 backup guard's "option A" (prefer a
    weaker cross-provider backup over none).

    A candidate must: resolve to a KNOWN maker DIFFERENT from the primary's, sit
    in an ``allowed_jurisdictions`` jurisdiction, and not be ``unavailable``.
    Ranking (deterministic, temp-0 safe): prefer the highest pricing tier that is
    still <= the primary's tier (a comparably-capable, not-pricier backup);
    if none sits at/below, take the closest tier above; break ties by higher
    output price then model id. Returns the catalog display NAME, or ``None`` when
    no cross-provider candidate qualifies (the caller then drops the backup).

    Jurisdiction is REQUIRED (not defaulted) because a substitute the user can't
    use in their region is worse than none — so a caller without the user's
    allowed set should not call this and should drop instead.
    """
    try:
        catalog = _load_catalog()
        primary = _resolve_model(primary_model, catalog)
    except (ValueError, BundledDocNotFoundError):
        return None
    primary_id = str(primary["id"])
    primary_provider = model_provider(primary_id)
    if primary_provider is None:
        return None
    primary_rank = pricing_tier_rank(pricing_tier(primary_id))
    allowed = {j.strip().lower() for j in allowed_jurisdictions if isinstance(j, str)}
    if not allowed:
        return None
    excluded = {m.strip() for m in (unavailable_models or []) if isinstance(m, str)}

    scored: list[tuple[bool, int, float, str, str]] = []
    for model in catalog.get("models", []):
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", ""))
        if not model_id or model_id == primary_id or model_id in excluded:
            continue
        if str(model.get("jurisdiction", "")).strip().lower() not in allowed:
            continue
        provider = model_provider(model_id)
        if provider is None or provider == primary_provider:
            continue
        if provider in _LOCAL_PROVIDERS:
            # Reachable only through a local runtime the user may not have.
            continue
        rank = pricing_tier_rank(pricing_tier(model_id))
        if rank is None:
            continue
        try:
            out_price = float(model.get("output_price_per_1m") or 0.0)
        except (TypeError, ValueError):
            out_price = 0.0
        # Sort key (descending): at/below primary tier first, then highest tier,
        # then priciest-in-tier, then id for a stable final tiebreak.
        at_or_below = primary_rank is None or rank <= primary_rank
        scored.append((at_or_below, rank, out_price, model_id, str(model.get("name", model_id))))

    if not scored:
        return None
    # When some candidates are at/below the primary tier, restrict to them and
    # take the highest such tier; otherwise fall back to the closest tier above
    # (the smallest rank among the all-above set).
    at_below = [s for s in scored if s[0]]
    if at_below:
        best = max(at_below, key=lambda s: (s[1], s[2], s[3]))
    else:
        # All candidates are pricier than the primary — take the CLOSEST (lowest
        # rank), then priciest-in-tier, then id.
        best = min(scored, key=lambda s: (s[1], -s[2], s[3]))
    return best[4]


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundledDocNotFoundError("catalog.json")
    return value


def _reject_fast_variant(model_id: str, catalog: dict[str, Any]) -> None:
    if not _FAST_SUFFIX_RE.search(model_id):
        return
    standard_id = _FAST_SUFFIX_RE.sub("", model_id).strip()
    try:
        resolved = _resolve_model(standard_id, catalog)
        standard_id = str(resolved["name"])
    except ValueError:
        pass
    raise AlternativeRejectedError(model_id, standard_id)


def _resolve_funding(
    method: dict[str, Any],
    catalog: dict[str, Any],
    user_context_text: str,
) -> tuple[str, dict[str, Any] | None]:
    billing = str(method.get("billing", ""))
    if billing == "per-token":
        return "per-token", None
    if billing == "local":
        # Funded iff the user-context declares the runtime present AND lists
        # the model as pulled (the model id is the estimate's subject; callers
        # pass it through `method["_model_id"]` — see _local_funding).
        return _local_funding(method, user_context_text), None

    funding_tiers = _tiers_funding_surface(catalog.get("subscription_tiers", []), str(method["id"]))
    active_subscriptions = _parse_active_subscriptions(user_context_text)
    active_tier = _match_active_tier(funding_tiers, active_subscriptions)

    if billing == "subscription-included":
        return ("subscription-included", active_tier) if active_tier else ("per-token", None)
    if billing == "subscription-pool":
        return ("subscription-pool", active_tier) if active_tier else ("per-token", None)
    if billing == "subscription-or-key":
        if active_tier is not None:
            return "subscription-or-key", active_tier
        api_keys = _parse_active_api_keys(user_context_text)
        provider = str(method.get("provider", "")).lower()
        if api_keys.get(provider, False):
            return "subscription-or-key", None
        return "per-token", None

    return "per-token", None


def _tiers_funding_surface(subscription_tiers: list[Any], surface_id: str) -> list[dict[str, Any]]:
    tiers: list[dict[str, Any]] = []
    for tier in subscription_tiers:
        if not isinstance(tier, dict):
            continue
        if surface_id in tier.get("surface_funded", []):
            tiers.append(tier)
    return tiers


def _match_active_tier(
    catalog_tiers: list[dict[str, Any]],
    active_subscriptions: list[tuple[str, str, float | None]],
) -> dict[str, Any] | None:
    for catalog_tier in catalog_tiers:
        catalog_name = _canonical_tier_name(str(catalog_tier.get("tier", "")))
        catalog_provider = str(catalog_tier.get("provider", "")).lower()
        catalog_monthly = catalog_tier.get("monthly_usd")
        for sub_name, sub_provider, sub_monthly in active_subscriptions:
            if _canonical_tier_name(sub_name) != catalog_name:
                continue
            if sub_provider and sub_provider != catalog_provider:
                continue
            if (
                isinstance(catalog_monthly, (int, float))
                and sub_monthly is not None
                and float(catalog_monthly) != sub_monthly
            ):
                continue
            return catalog_tier
    return None


def _canonical_tier_name(name: str) -> str:
    return _TIER_PAREN_RE.sub("", name).strip().lower()


def _parse_active_subscriptions(text: str) -> list[tuple[str, str, float | None]]:
    section = _extract_section(text, "Active subscriptions")
    return [
        (row[0], row[2].lower(), _parse_monthly_usd(row[1]))
        for row in _parse_markdown_table(section)
        if len(row) >= 3
    ]


def _parse_active_api_keys(text: str) -> dict[str, bool]:
    section = _extract_section(text, "Active API keys")
    keys: dict[str, bool] = {}
    for row in _parse_markdown_table(section):
        if len(row) < 2:
            continue
        provider = row[0].strip().lower()
        present = row[1].strip().lower() in {"yes", "y", "true", "✓", "x"}
        keys[provider] = present
    return keys


def _local_funding(method: dict[str, Any], user_context_text: str) -> str:
    """``local`` when the runtime is declared present AND the model the caller
    is estimating (``method["_model_id"]``, set by :func:`_with_model`) is in the
    pulled-models table; ``unfunded-local`` otherwise."""
    if not _local_runtime_present(user_context_text):
        return FUNDING_UNFUNDED_LOCAL
    model_id = str(method.get("_model_id", "")).strip()
    if model_id and model_id in _parse_local_models(user_context_text):
        return FUNDING_LOCAL
    return FUNDING_UNFUNDED_LOCAL


def _with_model(method: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Return a copy of ``method`` annotated with the model being estimated, so
    the funding resolver can check the pulled-models table for it."""
    return {**method, "_model_id": model_id}


# The user-context is UNTRUSTED text: every parser below is a bounded regex
# over Markdown table rows — no eval, no path derived from its contents.
_LOCAL_MODELS_HEADING: Final = "Local models (Ollama)"
_LOCAL_RUNTIME_ROW_RE: Final = re.compile(r"^\s*ollama\s+installed\s*$", re.IGNORECASE)
_LOCAL_MODEL_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,63}$")
_YES_VALUES: Final = frozenset({"yes", "y", "true", "✓", "x"})
# First-cell values of the section's header rows (both tables) — never a model.
_LOCAL_HEADER_CELLS: Final = frozenset({"runtime", "catalog model id", "model", "model id"})


def _local_runtime_present(text: str) -> bool:
    """True iff the "Local models (Ollama)" section carries an
    ``| Ollama installed | Yes |`` row. Absent section, absent row, or any
    non-yes value → False (the bundled example declares ``No``)."""
    section = _extract_section(text, _LOCAL_MODELS_HEADING)
    for row in _parse_markdown_table(section, keep_headers=True):
        if len(row) >= 2 and _LOCAL_RUNTIME_ROW_RE.match(row[0]):
            return row[1].strip().lower() in _YES_VALUES
    return False


def _parse_local_models(text: str) -> dict[str, str]:
    """Map catalog model id → pulled Ollama tag from the pulled-models table of
    the "Local models (Ollama)" section (``| Catalog model id | Tag pulled |
    Quantization | Notes |``). Tolerant of prose edits: any table row whose
    first cell looks like a catalog id counts; header rows, the presence row,
    separator rows and the commented example are skipped. Empty when the
    section is absent or lists nothing (the bundled example)."""
    section = _extract_section(text, _LOCAL_MODELS_HEADING)
    pulled: dict[str, str] = {}
    for row in _parse_markdown_table(section, keep_headers=True):
        if len(row) < 2:
            continue
        model_id = row[0].strip().strip("`").lower()
        if model_id in _LOCAL_HEADER_CELLS or _LOCAL_RUNTIME_ROW_RE.match(model_id):
            continue
        if not _LOCAL_MODEL_ID_RE.match(model_id):
            continue
        tag = row[1].strip().strip("`")
        if not tag or tag.lower() in {"tag pulled", "—", "-", "none", "n/a"}:
            continue
        pulled[model_id] = tag
    return pulled


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^#+\s+{re.escape(heading)}\s*\n(.*?)(?=^#+\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def _parse_markdown_table(section: str, *, keep_headers: bool = False) -> list[list[str]]:
    """Return the table rows of ``section`` (cells stripped, separator rows
    dropped). By default the FIRST row is dropped as the header, which assumes
    one table per section; ``keep_headers=True`` returns every row so a caller
    that reads a section with several tables can classify rows itself."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        match = _TABLE_ROW_RE.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if not cells or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(cells)
    if keep_headers:
        return rows
    return rows[1:] if rows else rows


def _parse_monthly_usd(value: str) -> float | None:
    match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _format_subscription_label(tier: dict[str, Any]) -> str:
    provider = str(tier.get("provider", "")).strip()
    name = str(tier.get("tier", "")).strip()
    monthly = tier.get("monthly_usd")
    if isinstance(monthly, (int, float)):
        return f"{provider} {name} ${float(monthly):g}/mo".strip()
    return f"{provider} {name}".strip()
