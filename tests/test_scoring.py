"""The deterministic scoring core (roadmodel.scoring).

Fixture catalog + benchmarks are tiny and hand-built so every expectation can
be reasoned about by hand; the properties below are the ones that make the
scorer trustworthy as the selector's arithmetic: monotone in quality, monotone
in cost, funding-aware, pool-aware, cross-provider backup with an honest
warning, deterministic, and explainable term by term.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from roadmodel import scoring

REPO_ROOT = Path(__file__).resolve().parent.parent


def _model(mid: str, name: str, inp: float, out: float, tiers: dict[str, str], juris: str = "us"):
    return {
        "id": mid,
        "name": name,
        "input_price_per_1m": inp,
        "output_price_per_1m": out,
        "tier_cost": "low",
        "tiers": {
            "coding": "B",
            "planning": "B",
            "agentic": "B",
            "multimodal": "B",
            "long-context": "B",
            "knowledge": "B",
            "speed": "B",
            **tiers,
        },
        "jurisdiction": juris,
    }


CATALOG = {
    "models": [
        _model("claude-opus-5", "Opus 5", 5.0, 25.0, {"coding": "S", "planning": "S"}),
        _model("claude-sonnet-5", "Sonnet 5", 2.0, 10.0, {"coding": "A", "planning": "A"}),
        _model("gpt-5.6-sol", "GPT-5.6 Sol", 4.0, 20.0, {"coding": "S", "planning": "S"}),
        _model("gpt-5.6-luna", "GPT-5.6 Luna", 0.2, 1.2, {"coding": "A", "planning": "A"}),
        _model("gemini-3.8-flash", "Gemini 3.8 Flash", 0.75, 3.5, {"coding": "A"}),
        _model("deepseek-flash", "DeepSeek Flash", 0.15, 0.6, {"coding": "A"}, juris="cn"),
    ],
    "access_methods": [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "provider": "anthropic",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["claude-opus-5", "claude-sonnet-5"],
        },
        {
            "id": "anthropic-api",
            "name": "Anthropic API",
            "provider": "anthropic",
            "provider_jurisdiction": "us",
            "billing": "per-token",
            "supports_models": ["claude-opus-5", "claude-sonnet-5"],
        },
        {
            "id": "codex-cli",
            "name": "Codex",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["gpt-5.6-sol", "gpt-5.6-luna"],
        },
        {
            "id": "openai-api",
            "name": "OpenAI API",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "per-token",
            "supports_models": ["gpt-5.6-sol", "gpt-5.6-luna"],
        },
        {
            "id": "google-api",
            "name": "Google API",
            "provider": "google",
            "provider_jurisdiction": "us",
            "billing": "per-token",
            "supports_models": ["gemini-3.8-flash"],
        },
        {
            "id": "deepseek-api",
            "name": "DeepSeek API",
            "provider": "deepseek",
            "provider_jurisdiction": "cn",
            "billing": "per-token",
            "supports_models": ["deepseek-flash"],
        },
    ],
    "subscription_tiers": [
        {
            "provider": "Anthropic",
            "tier": "claude.ai Max ($200)",
            "monthly_usd": 200.0,
            "surface_funded": ["claude-code"],
        },
        {
            "provider": "OpenAI",
            "tier": "ChatGPT Pro ($100)",
            "monthly_usd": 100.0,
            "surface_funded": ["codex-cli"],
        },
    ],
}

# AA figures: coding index + intelligence index for four models; Luna and the
# flashes are deliberately unmeasured on planning so the letter path is hit.
BENCH = {
    "claude-opus-5": {
        "evaluations": {
            "artificial_analysis_coding_index": 60,
            "artificial_analysis_intelligence_index": 50,
        }
    },
    "claude-sonnet-5": {
        "evaluations": {
            "artificial_analysis_coding_index": 45,
            "artificial_analysis_intelligence_index": 38,
        }
    },
    "gpt-5.6-sol": {
        "evaluations": {
            "artificial_analysis_coding_index": 59.5,
            "artificial_analysis_intelligence_index": 47,
        }
    },
    "gpt-5.6-luna": {
        "evaluations": {
            "artificial_analysis_coding_index": 44,
            "artificial_analysis_intelligence_index": 37,
        }
    },
    "gemini-3.8-flash": {
        "evaluations": {
            "artificial_analysis_coding_index": 46,
            "artificial_analysis_intelligence_index": 41,
        }
    },
}


def _context(
    *, subs: str, keys: str = "", headroom: str = "capped", pools: str = "", extra: str = ""
) -> str:
    return f"""# User Context

## Active subscriptions

| Subscription | Monthly | Provider | What it pays for |
| --- | --- | --- | --- |
{subs}

## Active API keys

| Provider | Key present | Notes |
| --- | --- | --- |
{keys}

## Budget priority and speed posture

**Budget priority:** `balanced`

**Consumption headroom:** `{headroom}`

## Usage-pool status

| Pool | Window | State | Resets | Notes |
| --- | --- | --- | --- | --- |
{pools}

## Allowed jurisdictions

**Allowed jurisdictions (in this file's user, today):**

`us, eu, uk`
{extra}
"""


MAX_ONLY = _context(subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |")
MAX_AND_PRO = _context(
    subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |\n| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
)
MAX_PRO_GOOGLE_KEY = _context(
    subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |\n| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
    keys="| Google | Yes | AI Studio key |",
)


def _rank(task: scoring.Task, text: str, **kw) -> scoring.Ranking:
    return scoring.rank(task, text, catalog=CATALOG, benchmarks=BENCH, **kw)


# --------------------------------------------------------------------------- #
# Funding and pools
# --------------------------------------------------------------------------- #


def test_unfunded_platforms_never_win_while_a_funded_one_exists() -> None:
    r = _rank(scoring.Task("coding", "low"), MAX_ONLY)
    assert r.primary is not None
    assert r.primary.funding == "subscription"
    assert r.primary.provider == "anthropic"
    # Every unfunded row (OpenAI / Google / DeepSeek paths) sorts after every funded one.
    seen_unfunded = False
    for c in r.candidates:
        if c.funding == "unfunded":
            seen_unfunded = True
        else:
            assert not seen_unfunded, "a funded candidate ranked below an unfunded one"


def test_single_provider_context_yields_backup_warning_not_an_unreachable_name() -> None:
    r = _rank(scoring.Task("coding", "medium"), MAX_ONLY)
    assert r.backup is None
    assert r.backup_warning is not None
    assert "funds only anthropic" in r.backup_warning


def test_second_subscription_becomes_the_backup_and_it_is_cross_provider() -> None:
    r = _rank(scoring.Task("coding", "medium"), MAX_AND_PRO)
    assert r.primary is not None and r.backup is not None
    assert r.backup.provider != r.primary.provider
    assert r.backup.funding != "unfunded"
    assert r.backup_warning is None


def test_exhausted_pool_moves_routine_work_to_the_other_funded_pool() -> None:
    """Exhausting the Claude pool (list price) must move routine work toward
    the funded Codex pool: the Opus-vs-Sol gap shrinks and Sol wins. (The
    fixture's evidence range is narrow, so absolute winners with both pools
    fresh are not asserted here — the movement is the property.)"""
    subs = (
        "| claude.ai Max ($200) | $200 | Anthropic | Claude Code |\n"
        "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |"
    )
    fresh = _rank(scoring.Task("coding", "low"), _context(subs=subs))
    exhausted = _rank(
        scoring.Task("coding", "low"),
        _context(
            subs=subs,
            pools="| claude.ai Max — weekly | 7 days | `exhausted` | Tue 20:00 | overflow on |",
        ),
    )

    def gap(r: scoring.Ranking) -> float:
        by = {c.model_id: c for c in r.candidates}
        return by["claude-opus-5"].score - by["gpt-5.6-sol"].score

    assert gap(exhausted) < gap(fresh)
    assert exhausted.primary is not None and exhausted.primary.provider == "openai"
    opus = next(c for c in exhausted.candidates if c.model_id == "claude-opus-5")
    assert opus.pool_state == "exhausted" and opus.scarcity == 1.0
    assert any("overflow bills at list price" in n for n in opus.notes)


def test_exhausted_pool_with_overflow_off_is_unfunded() -> None:
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        keys="| Anthropic | No | |",
        pools="| claude.ai Max — weekly | 7 days | `exhausted` | Tue 20:00 | overflow off |",
    )
    r = _rank(scoring.Task("coding", "low"), text)
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.funding == "unfunded"


def test_tight_pool_costs_more_than_headroom_but_less_than_exhausted() -> None:
    def scarcity(state: str) -> float:
        text = _context(
            subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
            pools=f"| claude.ai Max — weekly | 7 days | `{state}` | — | |",
        )
        r = _rank(scoring.Task("coding", "low"), text)
        return next(c for c in r.candidates if c.model_id == "claude-opus-5").scarcity

    assert scarcity("headroom") < scarcity("tight") < scarcity("exhausted")


def test_uncapped_headroom_is_free_and_runs_max_effort() -> None:
    r = _rank(
        scoring.Task("coding", "low"),
        _context(
            subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |", headroom="uncapped"
        ),
    )
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.scarcity == 0.0 and opus.effective_cost_usd == 0.0 and opus.cost_penalty == 0.0
    assert opus.effort == "max"
    # And the frontier model wins a trivial task outright — flat funding.
    assert r.primary is not None and r.primary.model_id == "claude-opus-5"


def test_api_key_funds_a_per_token_path_at_list_price() -> None:
    r = _rank(scoring.Task("coding", "low"), MAX_PRO_GOOGLE_KEY)
    flash = next(c for c in r.candidates if c.model_id == "gemini-3.8-flash")
    assert flash.funding == "api-key" and flash.scarcity == 1.0


def test_subscription_surface_preferred_over_key_at_equal_cost() -> None:
    # Pool exhausted => Claude Code and the Anthropic API both cost list price;
    # the tie goes to the subscription (agent) surface, not the raw API.
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        keys="| Anthropic | Yes | |",
        pools="| claude.ai Max — weekly | 7 days | `exhausted` | Tue 20:00 | overflow on |",
    )
    r = _rank(scoring.Task("planning", "high"), text)
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.platform_id == "claude-code"


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def test_jurisdiction_filter_excludes_models_and_records_why() -> None:
    r = _rank(scoring.Task("coding", "low"), MAX_AND_PRO)
    assert all(c.model_id != "deepseek-flash" for c in r.candidates)
    assert {"model": "deepseek-flash", "reason": "jurisdiction"} in r.excluded


def test_platform_allowlist_is_a_hard_filter() -> None:
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |\n| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
        extra="\n## Allowed / excluded platforms\n\n**platforms.allowed:** `claude-code`\n\n**platforms.excluded:** `codex-cli`\n",
    )
    r = _rank(scoring.Task("coding", "low"), text)
    assert {c.platform_id for c in r.candidates} == {"claude-code"}


def test_unavailable_models_are_excluded() -> None:
    r = _rank(scoring.Task("coding", "high"), MAX_AND_PRO, unavailable_models=["claude-opus-5"])
    assert all(c.model_id != "claude-opus-5" for c in r.candidates)
    assert {"model": "claude-opus-5", "reason": "unavailable"} in r.excluded


# --------------------------------------------------------------------------- #
# The score itself
# --------------------------------------------------------------------------- #


def test_score_is_quality_minus_penalties_term_by_term() -> None:
    r = _rank(scoring.Task("coding", "medium"), MAX_AND_PRO)
    for c in r.candidates:
        nudge = 0.5 if c.platform_id in scoring.AGENT_SURFACES else 0.0
        assert c.score == pytest.approx(
            c.quality - c.requirement_penalty - c.cost_penalty + nudge, abs=0.02
        )
        assert c.cost_penalty == pytest.approx(
            r.lam * r.k_points_per_decade * c.cost_decades, abs=0.05
        )


def test_requirement_penalty_bites_below_the_bar_and_is_soft() -> None:
    r = _rank(scoring.Task("coding", "high", novel=True), MAX_AND_PRO)
    luna = next(c for c in r.candidates if c.model_id == "gpt-5.6-luna")
    assert luna.requirement == scoring.REQUIREMENT_NOVEL
    assert luna.requirement_penalty > 0
    assert luna in r.candidates  # penalised, not removed


def test_unmeasured_letter_is_discounted_below_a_measured_equal_letter() -> None:
    # Sonnet 5 (A, measured) vs a synthetic unmeasured A model at the same price.
    cat = json.loads(json.dumps(CATALOG))
    cat["models"].append(_model("ghost-a", "Ghost A", 2.0, 10.0, {"coding": "A"}))
    cat["access_methods"][0]["supports_models"].append("ghost-a")
    r = scoring.rank(scoring.Task("coding", "low"), MAX_ONLY, catalog=cat, benchmarks=BENCH)
    ghost = next(c for c in r.candidates if c.model_id == "ghost-a")
    assert ghost.quality_source == "letter"
    assert ghost.quality == pytest.approx(scoring.LETTER_QUALITY["A"] - scoring.UNMEASURED_DISCOUNT)


def test_cheap_posture_weighs_cost_more_than_best() -> None:
    cheap = _rank(
        scoring.Task("coding", "high"),
        MAX_AND_PRO.replace("`balanced`", "`cheap`").replace("balanced", "cheap"),
    )
    best = _rank(scoring.Task("coding", "high", budget="best"), MAX_AND_PRO)
    opus_cheap = next(c for c in cheap.candidates if c.model_id == "claude-opus-5")
    opus_best = next(c for c in best.candidates if c.model_id == "claude-opus-5")
    assert cheap.lam > best.lam
    assert opus_cheap.cost_penalty > opus_best.cost_penalty


def test_harder_tasks_weigh_cost_less() -> None:
    lows = _rank(scoring.Task("coding", "low"), MAX_AND_PRO)
    highs = _rank(scoring.Task("coding", "high"), MAX_AND_PRO)
    novel = _rank(scoring.Task("coding", "high", novel=True), MAX_AND_PRO)
    assert lows.lam > highs.lam > novel.lam


def test_effort_ladder_follows_complexity_and_posture() -> None:
    assert scoring.effort_for(scoring.Task("coding", "low"), "capped", 0.35) == "low"
    assert scoring.effort_for(scoring.Task("coding", "medium"), "capped", 0.35) == "medium"
    assert scoring.effort_for(scoring.Task("coding", "high"), "capped", 0.35) == "high"
    assert scoring.effort_for(scoring.Task("coding", "high", novel=True), "capped", 0.35) == "xhigh"
    # Cross-cutting planning bumps a rung; `best` bumps a rung; `cheap` on a
    # costly path drops one; under capped the ladder tops out at xhigh.
    assert scoring.effort_for(scoring.Task("planning", "medium"), "capped", 0.35) == "high"
    assert (
        scoring.effort_for(scoring.Task("coding", "high", budget="best"), "capped", 0.35) == "xhigh"
    )
    assert (
        scoring.effort_for(scoring.Task("coding", "medium", budget="cheap"), "capped", 0.35)
        == "low"
    )
    assert (
        scoring.effort_for(
            scoring.Task("coding", "high", novel=True, budget="best"), "capped", 0.35
        )
        == "xhigh"
    )
    # `uncapped` on a free path is the only route to max.
    assert scoring.effort_for(scoring.Task("coding", "low"), "uncapped", 0.0) == "max"
    assert scoring.effort_for(scoring.Task("coding", "low"), "uncapped", 1.0) == "low"


def test_market_exchange_rate_is_positive_and_falls_back() -> None:
    k = scoring.market_exchange_rate(CATALOG, BENCH)
    assert k > 0
    assert scoring.market_exchange_rate(CATALOG, {}) == scoring.DEFAULT_K


def test_ranking_is_deterministic_and_json_round_trips() -> None:
    a = _rank(scoring.Task("coding", "medium"), MAX_PRO_GOOGLE_KEY).to_dict()
    b = _rank(scoring.Task("coding", "medium"), MAX_PRO_GOOGLE_KEY).to_dict()
    assert a == b
    assert json.loads(json.dumps(a)) == a
    assert a["primary"]["model_id"] == a["candidates"][0]["model_id"]


def test_task_validation() -> None:
    with pytest.raises(ValueError):
        scoring.Task("vibes", "low")
    with pytest.raises(ValueError):
        scoring.Task("coding", "extreme")
    with pytest.raises(ValueError):
        scoring.Task("coding", "low", budget="free")


def test_render_text_names_primary_backup_and_terms() -> None:
    text = scoring.render_text(_rank(scoring.Task("coding", "medium"), MAX_AND_PRO))
    assert "PRIMARY" in text and "BACKUP" in text
    assert "req-pen" in text and "cost-pen" in text and "effort" in text
    warn = scoring.render_text(_rank(scoring.Task("coding", "medium"), MAX_ONLY))
    assert "BACKUP   none" in warn


# --------------------------------------------------------------------------- #
# Real bundled data + CLI
# --------------------------------------------------------------------------- #


def test_bundled_benchmarks_load_and_real_catalog_ranks() -> None:
    bench = scoring._load_benchmarks()
    assert len(bench) > 20
    r = scoring.rank(scoring.Task("coding", "medium"), MAX_AND_PRO)
    assert r.primary is not None and r.backup is not None
    assert r.k_points_per_decade > 5


def test_cli_score_json(tmp_path: Path) -> None:
    ctx = tmp_path / "user-context.md"
    ctx.write_text(MAX_AND_PRO, encoding="utf-8")
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "roadmodel",
            "score",
            "--category",
            "coding",
            "--complexity",
            "high",
            "--novel",
            "--output",
            "json",
            "--top",
            "3",
            "--user-context",
            str(ctx),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(out.stdout)
    assert payload["task"] == {
        "category": "coding",
        "complexity": "high",
        "novel": True,
        "budget": "balanced",
    }
    assert len(payload["candidates"]) == 3
    assert payload["primary"]["provider"] != payload["backup"]["provider"]


# --------------------------------------------------------------------------- #
# Review-driven edge cases
# --------------------------------------------------------------------------- #


def test_zero_evidence_is_unmeasured_not_a_score() -> None:
    """AA reports 0 tokens/s for endpoints it has not throughput-tested; a 0
    must read as 'not measured', not as the slowest model in the catalog."""
    bench = {
        "claude-opus-5": {"median_output_tokens_per_second": 0, "evaluations": {}},
        "gpt-5.6-sol": {"median_output_tokens_per_second": 80, "evaluations": {}},
        "gpt-5.6-luna": {"median_output_tokens_per_second": 200, "evaluations": {}},
        "gemini-3.8-flash": {"median_output_tokens_per_second": 300, "evaluations": {}},
    }
    r = scoring.rank(scoring.Task("speed", "low"), MAX_AND_PRO, catalog=CATALOG, benchmarks=bench)
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.quality_source == "letter"
    assert opus.quality == pytest.approx(scoring.LETTER_QUALITY["B"] - scoring.UNMEASURED_DISCOUNT)
    assert scoring._evidence(bench, "claude-opus-5", "median_output_tokens_per_second") is None
    assert scoring._evidence(bench, "gpt-5.6-sol", "median_output_tokens_per_second") == 80


def test_k_is_fitted_in_the_scores_own_quality_units() -> None:
    """K must be the slope of the blended quality the score uses (0–100,
    stretched), not of the raw AA index — otherwise λ = 1 is far below the
    market line. Recompute the fit by hand from _quality."""
    task = scoring.Task("coding", "medium")
    scale = scoring._evidence_scale(CATALOG, BENCH, "artificial_analysis_coding_index")
    pts = []
    for m in CATALOG["models"]:
        q, source, _ = scoring._quality(m, task, BENCH, scale)
        if source != "letter":
            pts.append((math.log10(scoring.blended_price(m)), q))
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
    assert scoring.market_exchange_rate(CATALOG, BENCH, task, scale) == pytest.approx(slope)
    # Speed anti-correlates with price → falls back to the planning fit.
    assert scoring.market_exchange_rate(
        CATALOG, BENCH, scoring.Task("speed", "low")
    ) == pytest.approx(
        scoring.market_exchange_rate(CATALOG, BENCH, scoring.Task("planning", "low"))
    )


def test_local_ollama_model_is_a_free_candidate() -> None:
    cat = json.loads(json.dumps(CATALOG))
    cat["models"].append(_model("gemma3", "Gemma 3 27B", 0.0, 0.0, {"coding": "B"}))
    cat["access_methods"].append(
        {
            "id": "ollama",
            "name": "Ollama (local)",
            "provider": "ollama",
            "provider_jurisdiction": "local",
            "billing": "local",
            "supports_models": ["gemma3"],
        }
    )
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        extra=(
            "\n## Local models (Ollama)\n\n| Runtime | Present |\n| --- | --- |\n| Ollama installed | Yes |\n\n"
            "| Catalog model id | Ollama tag |\n| --- | --- |\n| gemma3 | gemma3:27b |\n"
        ),
    )
    r = scoring.rank(scoring.Task("coding", "low"), text, catalog=cat, benchmarks=BENCH)
    local = next(c for c in r.candidates if c.model_id == "gemma3")
    assert local.funding == "local" and local.scarcity == 0.0 and local.cost_penalty == 0.0
    assert local.platform_id == "ollama"


def test_platform_filters_accept_the_templates_fenced_form_and_drop_prose() -> None:
    fenced = "```text\nplatforms.allowed:   claude-code, codex-cli, anthropic-api\nplatforms.excluded:  cursor\n```"
    assert scoring.platform_filters(fenced) == (
        {"claude-code", "codex-cli", "anthropic-api"},
        {"cursor"},
    )
    placeholder = (
        "```text\nplatforms.allowed:   (none declared)\nplatforms.excluded:  (none declared)\n```"
    )
    assert scoring.platform_filters(placeholder) == (set(), set())
    bold = "**platforms.allowed:** `claude-code`\n\n**platforms.excluded:** `cursor`"
    assert scoring.platform_filters(bold) == ({"claude-code"}, {"cursor"})
    assert scoring.platform_filters("") == (set(), set())


def test_unknown_platform_ids_are_reported_and_ignored_not_allow_nothing() -> None:
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        extra="\n**platforms.allowed:** `claud-code`\n",  # typo
    )
    r = _rank(scoring.Task("coding", "low"), text)
    assert r.candidates, "a typo'd allowlist must not empty the candidate set"
    assert any(
        "unknown access-method id in platforms.allowed: claud-code" in e["reason"]
        for e in r.excluded
    )


def test_model_scoped_pool_row_applies_only_to_that_family() -> None:
    cat = json.loads(json.dumps(CATALOG))
    cat["models"].append(_model("claude-fable-5.1", "Fable 5.1", 10.0, 50.0, {"coding": "S"}))
    cat["access_methods"][0]["supports_models"].append("claude-fable-5.1")
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        pools=(
            "| claude.ai Max — weekly (all models) | 7 days | `headroom` | — | |\n"
            "| claude.ai Max — Fable 50% sub-cap | 7 days | **`tight`** (74%) | Tue | |"
        ),
    )
    r = scoring.rank(scoring.Task("coding", "high"), text, catalog=cat, benchmarks=BENCH)
    by_id = {c.model_id: c for c in r.candidates}
    assert by_id["claude-fable-5.1"].pool_state == "tight"
    assert by_id["claude-opus-5"].pool_state == "headroom"
    assert by_id["claude-sonnet-5"].pool_state == "headroom"


def test_provider_word_alone_does_not_attach_a_pool_row() -> None:
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        pools="| Anthropic API monthly budget | 30 days | `exhausted` | — | |",
    )
    r = _rank(scoring.Task("coding", "low"), text)
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.pool_state == "headroom"  # an API budget row is not the Max pool
    plan = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        pools="| Anthropic Max weekly | 7 days | `tight` | — | |",
    )
    r2 = _rank(scoring.Task("coding", "low"), plan)
    assert next(c for c in r2.candidates if c.model_id == "claude-opus-5").pool_state == "tight"


def test_exhausted_overflow_off_falls_back_to_a_declared_key() -> None:
    text = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |",
        keys="| Anthropic | Yes | |",
        pools="| claude.ai Max — weekly | 7 days | `exhausted` | Tue 20:00 | overflow off |",
    )
    r = _rank(scoring.Task("coding", "low"), text)
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
    assert opus.funding == "api-key" and opus.scarcity == 1.0
    assert any("running on the declared key" in n for n in opus.notes)


def test_effort_max_only_on_a_free_uncapped_path() -> None:
    assert (
        scoring.effort_for(scoring.Task("planning", "high", budget="best"), "uncapped", 1.0)
        == "xhigh"
    )
    assert (
        scoring.effort_for(scoring.Task("planning", "high", budget="best"), "uncapped", 0.7)
        == "xhigh"
    )
    assert (
        scoring.effort_for(scoring.Task("planning", "high", budget="best"), "uncapped", 0.0)
        == "max"
    )


def test_letter_only_category_is_not_discounted() -> None:
    r = _rank(scoring.Task("multimodal", "high"), MAX_AND_PRO)
    for c in r.candidates:
        assert c.quality_source == "letter"
        assert c.quality == pytest.approx(scoring.LETTER_QUALITY[c.letter])


def test_declared_budget_accepts_selector_aliases() -> None:
    assert scoring.declared_budget("**Budget priority:** `balanced` — quality wins") == "balanced"
    assert scoring.declared_budget("**Budget priority:** `quality`") == "best"
    assert scoring.declared_budget("**Budget priority:** cost") == "cheap"
    assert scoring.declared_budget("") == "balanced"


def test_jurisdiction_list_on_the_same_line_and_decorated_pool_states() -> None:
    assert scoring.allowed_jurisdictions("**Allowed jurisdictions:** `us, eu`") == {"us", "eu"}
    assert scoring.allowed_jurisdictions(
        "**Allowed jurisdictions (in this file's user, today):**\n\n`us, eu, uk`"
    ) == {"us", "eu", "uk"}
    assert scoring.allowed_jurisdictions("") == set(scoring.BASELINE_JURISDICTIONS)
    rows = scoring.pool_states(
        "## Usage-pool status\n\n| Pool | Window | State | Resets | Notes |\n| --- | --- | --- | --- | --- |\n"
        "| claude.ai Max — weekly | 7 days | **`exhausted`** (since Sun) | Tue | overflow on |\n"
    )
    assert rows == [("claude.ai Max — weekly", "exhausted", "overflow on")]


def test_cli_rejects_a_missing_user_context_path(tmp_path: Path) -> None:
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "roadmodel",
            "score",
            "--category",
            "coding",
            "--complexity",
            "low",
            "--user-context",
            str(tmp_path / "nope.md"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0
    assert "nope.md" in (out.stderr + out.stdout)


# --------------------------------------------------------------------------
# A Usage-pool row must not outlive its own reset.
#
# The operator writes `exhausted` when a cap binds and cannot be relied on to
# flip it back when the window rolls. On 2026-09-22 a row stamped
# "Tue 2026-09-22 20:00 EDT" was still routing every coding step off Claude a
# day after the pool had reset. Expiry is deliberately ASYMMETRIC: keeping a
# stale row costs quality, but expiring a LIVE one costs money (overflow bills
# at list price), so only a certainly-past reset expires a row.
# --------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402


def _pools(reset: str, state: str = "exhausted") -> str:
    return (
        "## Usage-pool status\n\n"
        "| Pool | Window | State | Resets (local time) | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| claude.ai Max — weekly | 7 days | `{state}` | {reset} | overflow on |\n"
    )


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_a_row_past_its_reset_reads_as_headroom_and_says_why() -> None:
    # 20:00 EDT on the 22nd is 00:00 UTC on the 23rd.
    rows = scoring.pool_states(_pools("Tue 2026-09-22 20:00 EDT"), now=_utc(2026, 9, 23, 0, 1))
    assert rows[0][1] == "headroom"
    assert "reset (Tue 2026-09-22 20:00 EDT) has passed" in rows[0][2]


def test_a_row_before_its_reset_keeps_its_declared_state() -> None:
    """One minute BEFORE 20:00 EDT: still exhausted. The zone is honoured —
    read as UTC this would already look past."""
    rows = scoring.pool_states(_pools("Tue 2026-09-22 20:00 EDT"), now=_utc(2026, 9, 22, 23, 59))
    assert rows[0][1] == "exhausted"


@pytest.mark.parametrize("reset", ["rolling", "Tue 20:00", "next week", ""])
def test_an_undated_reset_never_expires_a_row(reset: str) -> None:
    """Expiring a LIVE exhausted pool bills overflow at list price — the $500
    failure. Anything that does not name a date keeps its declared state."""
    rows = scoring.pool_states(_pools(reset), now=_utc(2030, 1, 1))
    assert rows[0][1] == "exhausted"


def test_an_unrecognised_zone_needs_a_full_day_of_margin() -> None:
    """No guessing at an unlisted zone: it counts only once no offset on earth
    could still leave the reset in the future."""
    cell = "2026-09-22 20:00 XYZ"
    assert scoring.pool_states(_pools(cell), now=_utc(2026, 9, 23, 1))[0][1] == "exhausted"
    assert scoring.pool_states(_pools(cell), now=_utc(2026, 9, 23, 21))[0][1] == "headroom"


def test_a_bare_date_waits_until_that_day_is_over_everywhere() -> None:
    cell = "2026-09-22"
    assert scoring.pool_states(_pools(cell), now=_utc(2026, 9, 23, 12))[0][1] == "exhausted"
    assert scoring.pool_states(_pools(cell), now=_utc(2026, 9, 24, 1))[0][1] == "headroom"


def test_tight_expires_like_exhausted_and_headroom_is_untouched() -> None:
    past = _utc(2026, 9, 30)
    tight = scoring.pool_states(_pools("2026-09-22 20:00 EDT", "tight"), now=past)
    assert tight[0][1] == "headroom"
    fresh = scoring.pool_states(_pools("2026-09-22 20:00 EDT", "headroom"), now=past)
    assert fresh[0] == ("claude.ai Max — weekly", "headroom", "overflow on")
