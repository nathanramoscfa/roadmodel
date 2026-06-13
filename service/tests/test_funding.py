# service/tests/test_funding.py
"""Phase 4.8 T2b — per-user funding user-context builder (app.funding).

Covers the catalog-derived builder that turns a user's declared funding (held
subscriptions + enabled API providers) into the user-context the recommender
LLM consumes for model SELECTION. The service PLUMBING (that this output is
threaded into recommend_structured) is pinned in test_recommend_endpoint.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import funding

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CATALOG = REPO_ROOT / "docs" / "catalog.json"

# Minimal synthetic catalog so the builder logic tests are hermetic (no
# dependency on catalog content). ids are chosen so _tier_id() resolves them:
# "claude.ai Max ($200)" -> legacy "claude-max"; "Cursor Ultra" -> "cursor-ultra".
_FAKE_CATALOG: dict[str, Any] = {
    "subscription_tiers": [
        {
            "provider": "Anthropic",
            "tier": "Claude Pro",
            "monthly_usd": 20.0,
            "surface_funded": ["claude-code", "claude-web"],
        },
        {
            "provider": "Anthropic",
            "tier": "claude.ai Max ($200)",
            "monthly_usd": 200.0,
            "surface_funded": ["claude-code", "claude-web"],
        },
        {
            "provider": "Cursor",
            "tier": "Cursor Ultra",
            "monthly_usd": 200.0,
            "surface_funded": ["cursor"],
        },
    ],
    "access_methods": [
        {
            "id": "anthropic-api",
            "provider": "anthropic",
            "billing": "per-token",
            "name": "Anthropic API",
        },
        {
            "id": "claude-code",
            "provider": "anthropic",
            "billing": "subscription-or-key",
            "name": "Claude Code",
        },
        {
            "id": "claude-web",
            "provider": "anthropic",
            "billing": "subscription-included",
            "name": "claude.ai web / desktop",
        },
        {"id": "cursor", "provider": "cursor", "billing": "subscription-pool", "name": "Cursor"},
        {
            "id": "deepseek-api",
            "provider": "deepseek",
            "billing": "per-token",
            "name": "DeepSeek API",
        },
    ],
}


# --- _tier_id: faithful port of web/lib/subscriptions.ts (slug-drift guard) ---


def test_tier_id_matches_web_slug_algorithm() -> None:
    """Pin the slug algorithm against web/lib/subscriptions.ts tierId() so a
    Python/TS drift (which would silently break subscription matching — the
    contract-drift failure class) fails loudly. Covers legacy ids, the "+"
    handling, the "($NNN)" strip, and the provider-prefix double."""
    assert funding._tier_id("Anthropic", "claude.ai Max ($200)") == "claude-max"
    assert funding._tier_id("Cursor", "Cursor Ultra") == "cursor-ultra"
    assert funding._tier_id("OpenAI", "ChatGPT Pro ($200)") == "chatgpt-pro"
    assert funding._tier_id("Anthropic", "Claude Pro") == "anthropic-claude-pro"
    assert funding._tier_id("Cursor", "Cursor Pro+") == "cursor-cursor-pro-plus"
    assert funding._tier_id("Google", "Google AI Ultra ($100)") == "google-google-ai-ultra-100"


# --- build_user_context ---


def test_lists_held_subscription_with_funded_surfaces() -> None:
    text = funding.build_user_context(["claude-max"], [], catalog=_FAKE_CATALOG)
    assert text is not None
    assert "## Active subscriptions" in text
    # Price disambiguator stripped to match the web Settings picker.
    assert "Claude Max" in text
    assert "Claude Max ($200)" not in text
    # Funded surfaces appear by display name + id.
    assert "Claude Code (`claude-code`)" in text
    assert "claude.ai web / desktop (`claude-web`)" in text
    # No API access declared.
    assert "## Active API access" in text
    # A subscription the user does NOT hold must not appear.
    assert "Cursor" not in text


def test_lists_enabled_api_provider() -> None:
    text = funding.build_user_context([], ["deepseek"], catalog=_FAKE_CATALOG)
    assert text is not None
    assert "DeepSeek" in text
    assert "deepseek-api" in text
    # No subscription held.
    assert "None declared." in text


def test_none_when_no_funding_declared() -> None:
    assert funding.build_user_context([], [], catalog=_FAKE_CATALOG) is None


def test_none_when_only_unresolvable_ids() -> None:
    # Stale / unknown ids resolve to nothing -> None (caller falls back to the
    # bundled template). Guards against silently emitting an empty context.
    text = funding.build_user_context(["not-a-tier"], ["not-a-provider"], catalog=_FAKE_CATALOG)
    assert text is None


def test_budget_and_jurisdiction_passthrough() -> None:
    text = funding.build_user_context(
        ["claude-max"],
        [],
        budget_priority="cost",
        allowed_jurisdictions=["us", "cn"],
        catalog=_FAKE_CATALOG,
    )
    assert text is not None
    assert "**Budget priority:** cost" in text
    assert "`us, cn`" in text


def test_budget_and_jurisdiction_defaults() -> None:
    text = funding.build_user_context(["claude-max"], [], catalog=_FAKE_CATALOG)
    assert text is not None
    assert "**Budget priority:** balanced" in text
    # Baseline allowed-jurisdictions list.
    assert "`us, eu, uk, ca, au, jp, kr`" in text


# --- user_context_from_request: extraction + short-circuit ---


@pytest.mark.parametrize(
    "context",
    [None, {}, {"subscriptions": [], "api_providers": []}, {"force_provider": "x"}],
)
def test_from_request_short_circuits_without_funding(context: dict[str, Any] | None) -> None:
    # No funding declared -> None (bundled template, free path unchanged). These
    # must NOT require a catalog load (they short-circuit before build).
    assert funding.user_context_from_request(context) is None


def test_from_request_coerces_non_list_fields() -> None:
    # A malformed (non-list) funding field is dropped, not crashed on.
    assert funding.user_context_from_request({"subscriptions": "claude-max"}) is None


def test_from_request_builds_against_real_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end against the repo's SSOT catalog: the ids the web stores resolve
    # to real funded surfaces (catches real-catalog drift, not just synthetic).
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(REAL_CATALOG))
    text = funding.user_context_from_request(
        {"subscriptions": ["claude-max"], "api_providers": ["deepseek"]}
    )
    assert text is not None
    assert "Claude Max" in text
    assert "claude-code" in text
    assert "DeepSeek" in text
