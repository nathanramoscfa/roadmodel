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
    "subscription-included": 0,
    "subscription-pool": 1,
    "subscription-or-key": 2,
    "per-token": 3,
}

_FAST_SUFFIX_RE: Final = re.compile(r"\s+Fast\s*$", re.IGNORECASE)
_TIER_PAREN_RE: Final = re.compile(r"\s*\(\$\d+(?:\.\d+)?\)\s*$")
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
) -> SessionCostEstimate:
    """Estimate a single (model, platform) session cost."""
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

    input_price = float(model["input_price_per_1m"])
    output_price = float(model["output_price_per_1m"])
    input_usd = input_tokens * input_price / 1_000_000.0 * input_multiplier
    output_usd = output_tokens * output_price / 1_000_000.0
    total_usd = input_usd + output_usd

    user_context_text = _load_user_context_text()
    funding_source, active_tier = _resolve_funding(method, catalog, user_context_text)
    subscription_label = _format_subscription_label(active_tier) if active_tier else None

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
) -> list[SessionCostEstimate]:
    user_context_text = _load_user_context_text()
    candidates: list[tuple[dict[str, Any], str]] = []
    for method in catalog.get("access_methods", []):
        if model_id not in method.get("supports_models", []):
            continue
        funding_source, _ = _resolve_funding(method, catalog, user_context_text)
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
        )
        for method, _ in top_three
    ]


def compare_alternatives_funding_rank(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    max_mode: bool = False,
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


# Pool aggregators — access-method providers that RESELL other companies' models
# rather than making them (Cursor's subscription pool). They must NOT be treated
# as a model's "maker" when resolving provider for the cross-provider backup
# guard: Opus 4.8 is reachable via Cursor, but its maker is Anthropic, and an
# Anthropic outage is what a backup must survive. A model reachable ONLY through
# an aggregator (e.g. Cursor's own Composer models) falls back to the aggregator
# provider, since in that case the aggregator IS the maker.
_AGGREGATOR_PROVIDERS: frozenset[str] = frozenset({"cursor"})


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
    if not first_party and len(supporting) == 1:
        # Reachable only through an aggregator → the aggregator is the maker.
        return next(iter(supporting))
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


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^#+\s+{re.escape(heading)}\s*\n(.*?)(?=^#+\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def _parse_markdown_table(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        match = _TABLE_ROW_RE.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if not cells or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(cells)
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
