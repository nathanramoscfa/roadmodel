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


def test_budget_postures_steer_selection_differently() -> None:
    """The lever's whole point: each budget priority must give the selector a
    DIFFERENT quality-vs-cost rule. Before this, all three emitted the same
    "quality wins, cost breaks ties" line, so Cost and Quality returned the same
    model (the reported bug). Assert the three selection instructions diverge and
    that Cost/Quality carry the expected opposing directives."""

    def posture(b: str) -> str:
        t = funding.build_user_context(["claude-max"], [], budget_priority=b, catalog=_FAKE_CATALOG)
        assert t is not None
        return t

    texts = {b: posture(b) for b in ("cheap", "balanced", "best")}
    # All three postures are distinct documents.
    assert len({t for t in texts.values()}) == 3
    # Cost differentiates by CAPABILITY TIER + EFFORT (not just price): when a
    # whole family is $0-funded, price is flat, so pick the smallest adequate
    # model at lowest effort, landing clearly BELOW the Quality pick — the fix
    # for the all-Max collapse where Cost held the frontier model at max effort.
    assert "differentiate by CAPABILITY TIER and EFFORT" in texts["cheap"]
    assert "SMALLEST / lowest-tier model" in texts["cheap"]
    assert "LOWEST reasoning effort" in texts["cheap"]
    assert "MUST land clearly BELOW it in capability tier and effort" in texts["cheap"]
    # ...only switching to a per-token model when it is genuinely cheaper.
    assert "genuinely cheaper in real dollars AND adequate" in texts["cheap"]
    # Quality steers UP (highest-quality outcome, top useful effort).
    assert "HIGHEST-QUALITY outcome" in texts["best"]
    assert "regardless of cost" in texts["best"]
    assert "highest USEFUL reasoning effort" in texts["best"]
    # Balanced is best-value, distinct from both extremes.
    assert "best VALUE" in texts["balanced"]
    # Every posture frames itself as an explicit override of the default
    # quality-first objective, so it takes effect from the appended context alone.
    for t in texts.values():
        assert "OVERRIDES any default" in t


def test_unknown_budget_id_falls_back_to_balanced_posture() -> None:
    # A stale / unexpected id must not crash or hard-code an extreme: echo the id
    # verbatim but apply the balanced posture.
    text = funding.build_user_context(
        ["claude-max"], [], budget_priority="cost", catalog=_FAKE_CATALOG
    )
    assert text is not None
    assert "**Budget priority:** cost" in text
    assert "best VALUE" in text  # balanced posture body


# --- consumption-headroom effort axis ---


_HEADROOM_MARK = "**Consumption headroom:** uncapped"


def test_headroom_auto_uncapped_for_top_tier_subscription() -> None:
    """A funded top-consumer-band tier (>= $200/mo, e.g. claude.ai Max $200)
    resolves `auto` to `uncapped`: the block is emitted and instructs MAX effort
    on all three picks with the picks differing by capability tier alone."""
    text = funding.build_user_context(["claude-max"], [], catalog=_FAKE_CATALOG)
    assert text is not None
    assert _HEADROOM_MARK in text
    assert "HIGHEST USEFUL reasoning effort" in text
    assert "ALL THREE priorities INCLUDING Cost" in text
    assert "CAPABILITY TIER ALONE" in text
    assert "never WHICH model is chosen" in text


def test_headroom_auto_capped_for_lower_tier_subscription() -> None:
    """A sub-$200 tier (Claude Pro at $20) stays `capped` under auto — no block,
    so effort keeps scaling down the ladder (the conservative default)."""
    text = funding.build_user_context(["anthropic-claude-pro"], [], catalog=_FAKE_CATALOG)
    assert text is not None
    assert "Consumption headroom" not in text


def test_headroom_explicit_uncapped_overrides_lower_tier() -> None:
    """Explicit `uncapped` forces the block even on a sub-$200 tier (the user
    declares they never hit their cap)."""
    text = funding.build_user_context(
        ["anthropic-claude-pro"],
        [],
        consumption_headroom="uncapped",
        catalog=_FAKE_CATALOG,
    )
    assert text is not None
    assert _HEADROOM_MARK in text


def test_headroom_explicit_capped_overrides_top_tier() -> None:
    """Explicit `capped` suppresses the block even on a $200 tier auto would
    call uncapped — the user opted to conserve budget."""
    text = funding.build_user_context(
        ["claude-max"], [], consumption_headroom="capped", catalog=_FAKE_CATALOG
    )
    assert text is not None
    assert "Consumption headroom" not in text


def test_headroom_block_coexists_with_budget_block() -> None:
    """The headroom block is additive: the budget-priority posture is still
    present, and the headroom override sits alongside it (effort axis vs the
    model/tier axis)."""
    text = funding.build_user_context(
        ["claude-max"], [], budget_priority="cheap", catalog=_FAKE_CATALOG
    )
    assert text is not None
    assert "**Budget priority:** cheap" in text
    assert _HEADROOM_MARK in text


def test_headroom_from_request_threads_through() -> None:
    """user_context_from_request reads consumption_headroom from the context dict
    and threads it into build_user_context."""
    monkey_ctx = {
        "subscriptions": ["anthropic-claude-pro"],
        "consumption_headroom": "uncapped",
        "allowed_jurisdictions": ["us"],
    }
    text = funding.user_context_from_request(monkey_ctx) or ""
    assert _HEADROOM_MARK in text


def test_effective_headroom_helper() -> None:
    tiers = _FAKE_CATALOG["subscription_tiers"]
    f = funding._effective_consumption_headroom
    assert f("uncapped", set(), tiers) == "uncapped"
    assert f("capped", {"claude-max"}, tiers) == "capped"
    assert f("auto", {"claude-max"}, tiers) == "uncapped"
    assert f(None, {"claude-max"}, tiers) == "uncapped"
    assert f("auto", {"anthropic-claude-pro"}, tiers) == "capped"
    assert f("auto", set(), tiers) == "capped"
    # Unknown/garbage value degrades to auto-derivation (conservative here).
    assert f("garbage", {"anthropic-claude-pro"}, tiers) == "capped"


def test_no_funding_explicit_budget_still_builds() -> None:
    # A signed-out user who actively picks Cost/Quality (non-default) must still
    # get the posture in the prompt even with zero declared funding — the lever
    # works signed-out. Funding sections render "None declared.".
    cheap = funding.build_user_context([], [], budget_priority="cheap", catalog=_FAKE_CATALOG)
    assert cheap is not None
    # Even with no declared funding, the Cost posture's tier+effort steering is
    # present (it applies whether or not a $0 family is held).
    assert "differentiate by CAPABILITY TIER and EFFORT" in cheap
    assert "None declared." in cheap
    # But the DEFAULT (balanced) with no funding stays on the bundled template
    # (None) — the highest-volume default path is unchanged.
    assert (
        funding.build_user_context([], [], budget_priority="balanced", catalog=_FAKE_CATALOG)
        is None
    )
    assert funding.build_user_context([], [], catalog=_FAKE_CATALOG) is None


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


def test_from_request_explicit_budget_builds_without_funding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An explicit non-default budget with NO funding must NOT short-circuit: the
    # signed-out Cost/Quality posture has to reach the selector. (Needs a catalog
    # since it now proceeds to build.)
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(REAL_CATALOG))
    text = funding.user_context_from_request({"budget_priority": "cheap"})
    assert text is not None
    assert "differentiate by CAPABILITY TIER and EFFORT" in text
    # Default budget with no funding still short-circuits (free path unchanged),
    # without needing a catalog load.
    assert funding.user_context_from_request({"budget_priority": "balanced"}) is None


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


# --- FundingGuard: funded-platform honesty guard (#444) ---

# The _FAKE_CATALOG above has: cursor (subscription-pool), claude-code
# (subscription-or-key), anthropic-api / deepseek-api (per-token).

_SECTIONS_CURSOR_FABRICATED = {
    "task": "A multi-file coding task.",
    "pick": "Fable 5 is S-tier in coding.",
    "run": "This runs on your Cursor subscription pool with Max Mode on.",
}


def _guard(subs: list[str], apis: list[str]) -> funding.FundingGuard:
    return funding.FundingGuard(subs, apis, catalog=_FAKE_CATALOG)


def test_guard_replaces_fabricated_subscription_claim() -> None:
    g = _guard([], ["deepseek"])
    rationale = (
        "TASK: A multi-file coding task. PICK: Fable 5 is S-tier in coding. "
        "RUN: This runs on your Cursor subscription pool with Max Mode on."
    )
    new_rationale, new_sections = g.sanitize("Cursor", rationale, dict(_SECTIONS_CURSOR_FABRICATED))
    assert new_sections is not None
    assert "your Cursor subscription" not in new_sections["run"]
    assert "not covered by any subscription or API access" in new_sections["run"]
    # Flat rationale is rebuilt in the same TASK/PICK/RUN shape.
    assert new_rationale is not None
    assert new_rationale.startswith("TASK: A multi-file coding task.")
    assert "your Cursor subscription" not in new_rationale
    # task/pick narration is untouched.
    assert new_sections["task"] == _SECTIONS_CURSOR_FABRICATED["task"]
    assert new_sections["pick"] == _SECTIONS_CURSOR_FABRICATED["pick"]


def test_guard_keeps_true_subscription_claim() -> None:
    # User actually holds claude-max, which funds claude-code: "your
    # subscription" narration on Claude Code is TRUE and must survive.
    g = _guard(["claude-max"], [])
    sections = {
        "task": "t",
        "pick": "p",
        "run": "This runs on your claude.ai Max subscription with High thinking.",
    }
    rationale = "TASK: t PICK: p RUN: This runs on your claude.ai Max subscription."
    new_rationale, new_sections = g.sanitize("Claude Code", rationale, sections)
    assert new_sections == sections
    assert new_rationale == rationale


def test_guard_leaves_honest_unfunded_note_alone() -> None:
    g = _guard([], ["deepseek"])
    sections = {
        "task": "t",
        "pick": "p",
        "run": "This requires an anthropic-api-key for pay-per-token use; unfunded pick.",
    }
    rationale = "TASK: t PICK: p RUN: honest."
    new_rationale, new_sections = g.sanitize("Anthropic API", rationale, sections)
    assert new_sections == sections
    assert new_rationale == rationale


def test_guard_key_reachable_replacement_names_the_provider() -> None:
    # DeepSeek API is per-token and the user enabled deepseek: a fabricated $0
    # claim is replaced with the honest pay-per-token-with-your-key wording.
    g = _guard([], ["deepseek"])
    sections = {"task": "t", "pick": "p", "run": "Runs at $0 marginal on your plan."}
    _, new_sections = g.sanitize("DeepSeek API", "TASK: t PICK: p RUN: r", sections)
    assert new_sections is not None
    assert "DeepSeek API key" in new_sections["run"]
    assert "pay-per-token" in new_sections["run"]


def test_guard_unknown_platform_gets_generic_replacement() -> None:
    g = _guard([], [])
    sections = {"task": "t", "pick": "p", "run": "Included in your Ultra plan."}
    _, new_sections = g.sanitize("Mystery Surface", None, sections)
    assert new_sections is not None
    assert "not covered by any subscription or API access" in new_sections["run"]


def test_guard_appends_correction_without_sections() -> None:
    g = _guard([], [])
    rationale = "Use Cursor; this is funded by the Cursor subscription pool."
    new_rationale, new_sections = g.sanitize("Cursor", rationale, None)
    assert new_sections is None
    assert new_rationale is not None
    assert new_rationale.startswith(rationale)
    assert "Correction:" in new_rationale


def test_guard_unfunded_word_is_not_a_claim() -> None:
    # \bfunded\b must not match "unfunded" — the honest disclaimer survives.
    g = _guard([], [])
    sections = {"task": "t", "pick": "p", "run": "This is an unfunded pick."}
    rationale = "TASK: t PICK: p RUN: This is an unfunded pick."
    new_rationale, new_sections = g.sanitize("Cursor", rationale, sections)
    assert new_sections == sections
    assert new_rationale == rationale


def test_guard_from_request_mirrors_context_short_circuit() -> None:
    # Anon / bundled-template path: guard OFF (that narration is by design).
    assert funding.funding_guard_from_request(None) is None
    assert funding.funding_guard_from_request({}) is None
    assert funding.funding_guard_from_request({"budget_priority": "balanced"}) is None


def test_guard_from_request_active_when_funding_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(REAL_CATALOG))
    g = funding.funding_guard_from_request({"api_providers": ["xai"]})
    assert g is not None
    # Real-catalog resolution: platform "xAI API" is key-reachable for this user.
    sections = {"task": "t", "pick": "p", "run": "Runs on your xAI subscription."}
    _, new_sections = g.sanitize("xAI API", None, sections)
    assert new_sections is not None
    assert "xAI API key" in new_sections["run"]


def test_guard_from_request_active_on_explicit_budget_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Non-default budget with no funding: the per-user doc IS injected (it says
    # "None declared"), so a funded claim there is a fabrication too.
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(REAL_CATALOG))
    g = funding.funding_guard_from_request({"budget_priority": "best"})
    assert g is not None
    sections = {"task": "t", "pick": "p", "run": "Runs on your Cursor subscription."}
    _, new_sections = g.sanitize("Cursor", None, sections)
    assert new_sections is not None
    assert "not covered by any subscription or API access" in new_sections["run"]


def test_guard_zai_provider_label() -> None:
    # z.ai renders as "z.ai", not the capitalized fallback "Zai" (#444 rider).
    assert funding._provider_label("zai") == "z.ai"


def test_guard_catches_possessive_free_subscription_claim() -> None:
    # Prod escape (2026-07-17): "the ChatGPT subscription" carries no "your",
    # so the possessive patterns missed it. The verb+"the" alternation must
    # catch it — and its Cursor/plan siblings.
    g = _guard([], ["deepseek"])
    for run in (
        "This uses the ChatGPT subscription via the Codex CLI with High thinking.",
        "This runs on the Cursor subscription with default thinking.",
        "Covered by the Max plan at no extra cost.",
    ):
        _, new_sections = g.sanitize("Cursor", None, {"task": "t", "pick": "p", "run": run})
        assert new_sections is not None
        assert "not covered by any subscription or API access" in new_sections["run"], run


def test_guard_honest_requires_a_subscription_phrasing_survives() -> None:
    # The engine's honest unfunded wording uses the article "a" and no
    # verb+"the" — it must NOT be treated as a funded claim.
    g = _guard([], [])
    sections = {
        "task": "t",
        "pick": "p",
        "run": "This is an unfunded pick requiring a pay-per-token API key or subscription.",
    }
    rationale = "TASK: t PICK: p RUN: unchanged."
    new_rationale, new_sections = g.sanitize("Anthropic API", rationale, sections)
    assert new_sections == sections
    assert new_rationale == rationale


# --- Access restriction: accessible-set + AccessGuard (#445) ---

# Extend the synthetic catalog with models + access-method supports so the
# accessible-set logic is hermetic. mistral-api (per-token, eu) supports two
# models; a cn model is present to exercise jurisdiction intersection.
_ACCESS_CATALOG: dict[str, Any] = {
    "subscription_tiers": _FAKE_CATALOG["subscription_tiers"],
    "access_methods": [
        {
            "id": "mistral-api",
            "provider": "mistral",
            "billing": "per-token",
            "name": "Mistral API",
            "provider_jurisdiction": "eu",
            "supports_models": ["mistral-small", "mistral-large"],
        },
        {
            "id": "deepseek-api",
            "provider": "deepseek",
            "billing": "per-token",
            "name": "DeepSeek API",
            "provider_jurisdiction": "cn",
            "supports_models": ["deepseek-pro"],
        },
        {
            "id": "claude-code",
            "provider": "anthropic",
            "billing": "subscription-or-key",
            "name": "Claude Code",
            "provider_jurisdiction": "us",
            "supports_models": ["opus"],
        },
    ],
    "models": [
        {
            "id": "mistral-small",
            "name": "Mistral Small",
            "jurisdiction": "eu",
            "output_price_per_1m": 0.3,
            "tiers": {"coding": "C", "planning": "C"},
        },
        {
            "id": "mistral-large",
            "name": "Mistral Large",
            "jurisdiction": "eu",
            "output_price_per_1m": 1.5,
            "tiers": {"coding": "B", "planning": "A"},
        },
        {
            "id": "deepseek-pro",
            "name": "DeepSeek Pro",
            "jurisdiction": "cn",
            "output_price_per_1m": 0.9,
            "tiers": {"coding": "A", "planning": "A"},
        },
        {
            "id": "opus",
            "name": "Opus",
            "jurisdiction": "us",
            "output_price_per_1m": 25.0,
            "tiers": {"coding": "S", "planning": "S"},
        },
    ],
}


def test_accessible_ids_none_without_funding() -> None:
    assert funding.accessible_model_ids([], [], catalog=_ACCESS_CATALOG) is None


def test_accessible_ids_by_api_provider_intersects_jurisdiction() -> None:
    # mistral declared, default (non-cn) jurisdictions -> both eu mistral models;
    # deepseek NOT declared, and cn excluded anyway.
    acc = funding.accessible_model_ids(
        [], ["mistral"], allowed_jurisdictions=["us", "eu"], catalog=_ACCESS_CATALOG
    )
    assert acc == {"mistral-small", "mistral-large"}


def test_accessible_ids_cn_dropped_by_default_jurisdiction() -> None:
    # deepseek declared but its model is cn; default jurisdiction excludes cn.
    acc = funding.accessible_model_ids(
        [], ["deepseek"], allowed_jurisdictions=["us", "eu"], catalog=_ACCESS_CATALOG
    )
    assert acc == set()


def test_accessible_ids_cn_included_when_allowed() -> None:
    acc = funding.accessible_model_ids(
        [], ["deepseek"], allowed_jurisdictions=["us", "eu", "cn"], catalog=_ACCESS_CATALOG
    )
    assert acc == {"deepseek-pro"}


def test_accessible_ids_by_subscription_surface() -> None:
    # Holding claude-max funds claude-code, which supports opus.
    acc = funding.accessible_model_ids(
        ["claude-max"], [], allowed_jurisdictions=["us"], catalog=_ACCESS_CATALOG
    )
    assert acc == {"opus"}


def test_user_context_includes_access_restriction_allowlist() -> None:
    text = funding.build_user_context(
        [], ["mistral"], allowed_jurisdictions=["us", "eu"], catalog=_ACCESS_CATALOG
    )
    assert text is not None
    assert "## Access restriction" in text
    assert "Access restriction (HARD)" in text
    assert "Mistral Small" in text and "Mistral Large" in text
    # A model the user cannot access is not listed as permitted.
    assert "Opus" not in text


def test_user_context_access_restriction_empty_set_message() -> None:
    # deepseek declared but cn excluded -> no accessible model -> the "enable a
    # provider" guidance instead of an allowlist.
    text = funding.build_user_context(
        [], ["deepseek"], allowed_jurisdictions=["us", "eu"], catalog=_ACCESS_CATALOG
    )
    assert text is not None
    assert "NO catalogued model in an allowed jurisdiction" in text


def _access_guard(subs: list[str], apis: list[str], juris: list[str]) -> funding.AccessGuard:
    acc = funding.accessible_model_ids(
        subs, apis, allowed_jurisdictions=juris, catalog=_ACCESS_CATALOG
    )
    assert acc is not None
    tiers = _ACCESS_CATALOG["subscription_tiers"]
    funded = funding._funded_surface_ids(tiers, set(subs))
    return funding.AccessGuard(acc, apis, funded, catalog=_ACCESS_CATALOG)


def test_access_guard_substitutes_inaccessible_primary() -> None:
    g = _access_guard([], ["mistral"], ["us", "eu"])
    r: dict[str, Any] = {
        "model": "Opus",
        "platform": "Claude Code",
        "settings": {},
        "backup": None,
        "rationale_sections": {"task": "t", "pick": "p", "run": "r"},
    }
    changed = g.enforce(r, "best")
    assert changed is True
    assert r["model"] in {"Mistral Small", "Mistral Large"}
    assert r["platform"] == "Mistral API"
    assert "outside your access" in r["rationale_sections"]["pick"]
    assert r["access_guard"]["action"] == "substituted"


def test_access_guard_best_picks_highest_quality_accessible() -> None:
    g = _access_guard([], ["mistral"], ["us", "eu"])
    r: dict[str, Any] = {
        "model": "Opus",
        "platform": "Claude Code",
        "settings": {},
        "backup": None,
        "rationale_sections": None,
    }
    g.enforce(r, "best")
    # Mistral Large outranks Mistral Small on tier points.
    assert r["model"] == "Mistral Large"


def test_access_guard_cheap_picks_cheapest_accessible() -> None:
    g = _access_guard([], ["mistral"], ["us", "eu"])
    r: dict[str, Any] = {"model": "Opus", "platform": "Claude Code", "settings": {}, "backup": None}
    g.enforce(r, "cheap")
    assert r["model"] == "Mistral Small"  # $0.3 < $1.5


def test_access_guard_leaves_accessible_pick_untouched() -> None:
    g = _access_guard([], ["mistral"], ["us", "eu"])
    r: dict[str, Any] = {
        "model": "Mistral Large",
        "platform": "Mistral API",
        "settings": {},
        "backup": None,
        "rationale_sections": {"task": "t", "pick": "p", "run": "r"},
    }
    changed = g.enforce(r, "best")
    assert changed is False
    assert r["model"] == "Mistral Large"
    assert r["rationale_sections"] == {"task": "t", "pick": "p", "run": "r"}


def test_access_guard_substitutes_inaccessible_backup() -> None:
    g = _access_guard([], ["mistral"], ["us", "eu"])
    r: dict[str, Any] = {
        "model": "Mistral Large",
        "platform": "Mistral API",
        "settings": {},
        "backup": "Opus",
        "rationale_sections": None,
    }
    g.enforce(r, "best")
    # Backup Opus is inaccessible -> substituted to a different-maker accessible
    # model; only mistral is accessible here, same maker -> dropped.
    assert r["backup"] is None


def test_access_guard_empty_accessible_set_is_noop() -> None:
    # deepseek declared, cn excluded -> empty accessible set -> cannot substitute.
    g = _access_guard([], ["deepseek"], ["us", "eu"])
    r: dict[str, Any] = {
        "model": "Opus",
        "platform": "Claude Code",
        "settings": {},
        "backup": None,
        "rationale_sections": {"task": "t", "pick": "p", "run": "r"},
    }
    changed = g.enforce(r, "best")
    assert changed is False
    assert r["model"] == "Opus"  # unchanged; user-context prose flags it


# --- Aggregator-aware maker + funded-cost-aware Cost substitution (dogfood) ---

# `nano` is reachable via BOTH the Cursor pool (listed FIRST) and OpenAI's own
# API, so the OLD first-method-wins maker resolution returned "cursor"; the fix
# must return the real maker "openai". `composer` is Cursor-only (aggregator IS
# the maker). `haiku` is funded at $0 via claude-max; `nano` is cheaper on RAW
# price but pay-per-token — the Cost pick must prefer the funded one.
_AGG_CATALOG: dict[str, Any] = {
    "subscription_tiers": [
        {
            "provider": "Anthropic",
            "tier": "claude.ai Max ($200)",
            "monthly_usd": 200.0,
            "surface_funded": ["claude-code"],
        },
        {
            "provider": "OpenAI",
            "tier": "ChatGPT Plus",
            "monthly_usd": 20.0,
            "surface_funded": ["chatgpt-app"],
        },
    ],
    "access_methods": [
        {
            "id": "cursor",
            "provider": "cursor",
            "billing": "subscription-pool",
            "name": "Cursor",
            "provider_jurisdiction": "us",
            "supports_models": ["nano", "composer"],
        },
        {
            "id": "openai-api",
            "provider": "openai",
            "billing": "per-token",
            "name": "OpenAI API",
            "provider_jurisdiction": "us",
            "supports_models": ["nano", "mini"],
        },
        {
            "id": "chatgpt-app",
            "provider": "openai",
            "billing": "subscription-included",
            "name": "ChatGPT",
            "provider_jurisdiction": "us",
            "supports_models": ["mini"],
        },
        {
            "id": "claude-code",
            "provider": "anthropic",
            "billing": "subscription-or-key",
            "name": "Claude Code",
            "provider_jurisdiction": "us",
            "supports_models": ["haiku"],
        },
    ],
    "models": [
        {
            "id": "nano",
            "name": "Nano",
            "jurisdiction": "us",
            "output_price_per_1m": 0.4,
            "tiers": {"coding": "C"},
        },
        {
            "id": "mini",
            "name": "Mini",
            "jurisdiction": "us",
            "output_price_per_1m": 2.0,
            "tiers": {"coding": "B"},
        },
        {
            "id": "composer",
            "name": "Composer",
            "jurisdiction": "us",
            "output_price_per_1m": 2.5,
            "tiers": {"coding": "B"},
        },
        {
            "id": "haiku",
            "name": "Haiku",
            "jurisdiction": "us",
            "output_price_per_1m": 4.0,
            "tiers": {"coding": "B"},
        },
    ],
}


def _agg_guard(subs: list[str], apis: list[str]) -> funding.AccessGuard:
    acc = funding.accessible_model_ids(
        subs, apis, allowed_jurisdictions=["us"], catalog=_AGG_CATALOG
    )
    assert acc is not None
    funded = funding._funded_surface_ids(_AGG_CATALOG["subscription_tiers"], set(subs))
    return funding.AccessGuard(acc, apis, funded, catalog=_AGG_CATALOG)


def test_maker_resolution_excludes_pool_aggregator() -> None:
    """Fix 1: a model reachable via the Cursor pool (listed FIRST) AND its own
    provider resolves to its REAL maker, not the aggregator — so this guard's
    cross-provider check agrees with roadmodel.cost.model_provider."""
    g = _agg_guard(["claude-max", "openai-chatgpt-plus"], ["openai", "anthropic"])
    assert g._maker_of[g._resolve_id("Nano")] == "openai"  # not "cursor"
    assert g._maker_of[g._resolve_id("Composer")] == "cursor"  # aggregator-only


def test_backup_same_maker_via_aggregator_is_caught() -> None:
    """Fix 1 end-to-end: primary Nano (openai, reachable via the Cursor pool) +
    backup Mini (openai) is a same-REAL-maker pair the old resolver missed
    (Nano->cursor != Mini->openai). Now caught and substituted cross-provider."""
    g = _agg_guard(["claude-max", "openai-chatgpt-plus"], ["openai", "anthropic"])
    r: dict[str, Any] = {
        "model": "Nano",
        "platform": "OpenAI API",
        "settings": {},
        "backup": "Mini",
    }
    g.enforce(r, "cheap")
    assert r["backup"] is not None
    assert g._maker_of.get(g._resolve_id(r["backup"]) or "") != "openai"


def test_cheap_substitute_prefers_funded_over_cheaper_paid() -> None:
    """Fix 3: the Cost substitute prefers a $0-funded model (Haiku via claude-max)
    over a cheaper-on-raw-price pay-per-token one (Nano $0.4). Before, raw price
    won and the Cost pick charged real cash when a funded model was free."""
    g = _agg_guard(["claude-max"], ["openai"])  # funds Haiku; OpenAI API = paid Nano/Mini
    r: dict[str, Any] = {"model": "Composer", "platform": "Cursor", "settings": {}, "backup": None}
    g.enforce(r, "cheap")  # Composer (Cursor) inaccessible -> substitute
    assert r["model"] == "Haiku"


def test_cheap_substitute_unchanged_without_any_funded_model() -> None:
    """Regression: with no funded subscription (API-only), the Cost substitute is
    still the cheapest raw-price accessible model — Fix 3 is a no-op here."""
    g = _agg_guard([], ["openai"])  # OpenAI API only: Nano ($0.4) + Mini ($2.0)
    r: dict[str, Any] = {"model": "Composer", "platform": "Cursor", "settings": {}, "backup": None}
    g.enforce(r, "cheap")
    assert r["model"] == "Nano"


def test_platform_for_prefers_funded_surface_over_paid_api() -> None:
    """A model reachable via BOTH a $0-funded subscription surface and a
    pay-per-token API surface shows the FUNDED one ("your cost to you") — Haiku on
    Claude Code (via Max), never a paid API. `mini` (funded via ChatGPT app) also
    resolves to the funded surface over the OpenAI API."""
    g = _agg_guard(["claude-max", "openai-chatgpt-plus"], ["openai", "anthropic"])
    assert g.platform_for("Haiku") == "Claude Code"
    assert g.platform_for("Mini") == "ChatGPT"  # funded via ChatGPT Plus, not "OpenAI API"


# --- Backup enrichment (its own funded platform + per-surface settings) -------


def test_reasoning_level_reads_the_pick_effort() -> None:
    from app.recommend import _reasoning_level

    assert _reasoning_level({"effort": "Max", "thinking": "On"}) == "Max"
    assert _reasoning_level({"intelligence": "XHigh"}) == "XHigh"
    assert _reasoning_level({"effort": "Ultracode", "thinking": "On"}) == "Ultracode"
    assert _reasoning_level({"max_mode": "OFF", "thinking": "High"}) == "High"
    assert _reasoning_level({"max_mode": "ON", "thinking": "On"}) is None  # Cursor: no level
    assert _reasoning_level({}) is None


def test_build_backup_enriches_with_funded_platform_and_posture_settings() -> None:
    """The backup gets its OWN funded platform + per-surface settings at the same
    reasoning posture as the pick — so it adheres to the user's settings, not a
    bare name."""
    from app.recommend import _build_backup

    g = _agg_guard(["claude-max"], ["openai"])
    result = {"model": "Nano", "settings": {"intelligence": "XHigh"}, "backup": "Haiku"}
    b = _build_backup(result, g)
    assert b is not None
    assert b.model == "Haiku"
    assert b.platform == "Claude Code"  # $0 funded, not a paid API
    # The pick's XHigh posture rendered for the backup's Claude Code surface.
    assert b.settings == {"effort": "XHigh", "thinking": "On"}


def test_build_backup_ultracode_clamps_to_max_on_cross_provider_surface() -> None:
    from app.recommend import _build_backup

    g = _agg_guard(["claude-max"], ["openai"])
    result = {
        "model": "Nano",
        "settings": {"effort": "Ultracode", "thinking": "On"},
        "backup": "Haiku",
    }
    b = _build_backup(result, g)
    assert b is not None and b.settings.get("effort") == "Max"


def test_build_backup_none_and_anon() -> None:
    from app.recommend import _build_backup

    assert _build_backup({"backup": None}, None) is None
    # Anon (no AccessGuard): name only, platform/settings unresolved.
    b = _build_backup({"model": "X", "settings": {"effort": "Max"}, "backup": "GPT-5.5"}, None)
    assert b is not None and b.model == "GPT-5.5" and b.platform is None and b.settings == {}


def test_access_guard_from_request_none_without_funding() -> None:
    assert funding.access_guard_from_request(None) is None
    assert funding.access_guard_from_request({}) is None
    assert funding.access_guard_from_request({"budget_priority": "best"}) is None


def test_access_guard_from_request_active_with_funding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(REAL_CATALOG))
    g = funding.access_guard_from_request(
        {"api_providers": ["mistral", "xai"], "allowed_jurisdictions": ["us", "eu"]}
    )
    assert g is not None
    # A real-catalog frontier leak is substituted to an accessible low-tier model.
    r: dict[str, Any] = {
        "model": "Fable 5",
        "platform": "Claude Code",
        "settings": {},
        "backup": None,
        "rationale_sections": {"task": "t", "pick": "p", "run": "r"},
    }
    changed = g.enforce(r, "best")
    assert changed is True
    assert not g.is_accessible("Fable 5")
    assert g.is_accessible(r["model"])
