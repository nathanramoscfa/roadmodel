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
}

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


def build_user_context(
    subscriptions: list[str],
    api_providers: list[str],
    *,
    budget_priority: str | None = None,
    allowed_jurisdictions: list[str] | None = None,
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

    if not held_lines and not api_lines:
        return None

    budget = _DEFAULT_BUDGET_PRIORITY
    if isinstance(budget_priority, str) and budget_priority:
        budget = budget_priority
    juris = allowed_jurisdictions if allowed_jurisdictions else list(_BASELINE_JURISDICTIONS)

    held_block = "\n".join(held_lines) if held_lines else "- None declared."
    api_block = "\n".join(api_lines) if api_lines else "- None declared."

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

**Budget priority:** {budget} — quality wins per `<objective>`; cost only
breaks an exact quality tie, and on a tie a $0 held subscription beats new
pay-per-token spend. Treat the subscriptions above as sunk cost.

**Speed posture:** not a valued dimension unless the prompt states an explicit
latency requirement.

## Allowed jurisdictions

`{", ".join(juris)}`
"""


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
    if not subscriptions and not api_providers:
        return None

    budget_raw = context.get("budget_priority")
    budget_priority = budget_raw if isinstance(budget_raw, str) else None
    allowed_jurisdictions = _str_list(context.get("allowed_jurisdictions")) or None

    try:
        return build_user_context(
            subscriptions,
            api_providers,
            budget_priority=budget_priority,
            allowed_jurisdictions=allowed_jurisdictions,
        )
    except Exception:  # noqa: BLE001 - funding context is best-effort, never fatal
        # A catalog read/parse failure must not turn a good request into a 500;
        # degrade to the bundled template (the pre-T2b behavior).
        logger.warning("per-user funding context build failed (non-fatal)", exc_info=True)
        return None
