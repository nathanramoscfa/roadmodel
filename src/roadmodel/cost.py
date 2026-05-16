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
