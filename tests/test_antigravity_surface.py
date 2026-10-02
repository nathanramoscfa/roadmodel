"""Antigravity is a catalog surface (2026-10-01).

Google moved Google AI Pro, Ultra and free personal accounts off the Gemini CLI
to Antigravity on 2026-06-18, but the catalog kept saying those plans fund the
Gemini CLI and had no Antigravity method at all, so the operator's user-context
had to carry Antigravity's model lineup by hand. The catalog now owns it: the
`antigravity` method lists what Antigravity serves, the catalog cron refreshes
that list like every other surface's, and the Google plans fund the surfaces
they actually reach.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from roadmodel import cost

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "docs" / "catalog.json").read_text(encoding="utf-8"))
METHODS = {m["id"]: m for m in CATALOG["access_methods"]}
TIERS = {t["tier"]: t for t in CATALOG["subscription_tiers"] if t["provider"] == "Google"}


def test_antigravity_is_a_google_surface_serving_catalogued_models() -> None:
    ag = METHODS["antigravity"]
    assert ag["provider"] == "google" and ag["billing"] == "subscription-included"
    model_ids = {m["id"] for m in CATALOG["models"]}
    assert set(ag["supports_models"]) <= model_ids
    # Gemini, plus the third-party models Antigravity serves on Google's quota.
    assert {"gemini-3.8-flash", "gemini-3.1-pro", "sonnet-4.6", "gpt-oss-120b"} <= set(
        ag["supports_models"]
    )


def test_google_plans_fund_the_surfaces_they_reach() -> None:
    for name in ("Google AI Pro", "Google AI Ultra ($100)", "Google AI Ultra ($200)"):
        assert TIERS[name]["surface_funded"] == ["antigravity", "gemini-app"], name
    # Plus gets only Antigravity's free tier, which needs no subscription.
    assert TIERS["Google AI Plus"]["surface_funded"] == ["gemini-app"]
    # Since 2026-06-18 the Gemini CLI takes a Gemini API key only.
    assert not any("gemini-cli" in t["surface_funded"] for t in CATALOG["subscription_tiers"])
    assert METHODS["gemini-cli"]["billing"] == "per-token"


def test_a_google_ai_pro_user_context_funds_antigravity() -> None:
    """The operator's row reads "$20"; the catalog has $19.99."""
    text = (
        "## Active subscriptions\n\n"
        "| Subscription | Monthly | Provider | What it pays for |\n"
        "| --- | --- | --- | --- |\n"
        "| Google AI Pro | $20 | Google | Antigravity |\n\n"
        "## Active API keys\n\n"
        "| Provider | Key present | Notes |\n| --- | --- | --- |\n"
    )
    funding, tier = cost._resolve_funding(METHODS["antigravity"], CATALOG, text)
    assert funding == "subscription-included" and tier is not None
    assert tier["tier"] == "Google AI Pro"
    # The Gemini CLI is not funded by the plan.
    assert cost._resolve_funding(METHODS["gemini-cli"], CATALOG, text)[0] == "per-token"


def test_the_catalog_cron_keeps_antigravity_current() -> None:
    prompt = re.sub(r"\s+", " ", (ROOT / "update" / "prompt.md").read_text(encoding="utf-8"))
    # The hardcoded provider → surfaces mapping, per Google tier.
    assert (
        "`google` → `gemini-app, antigravity` for Google AI Pro and every Google AI Ultra tier"
        in prompt
    )
    assert "`gemini-app` alone for every other Google tier" in prompt
    assert "`gemini-cli` is never a subscription surface" in prompt
    # The supports-models refresh has a query for it.
    assert "`antigravity` → `Antigravity models site:antigravity.google`" in prompt
