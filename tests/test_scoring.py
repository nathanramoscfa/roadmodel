"""The deterministic scoring core (roadmodel.scoring).

Fixture catalog + benchmarks are tiny and hand-built so every expectation can
be reasoned about by hand; the properties below are the ones that make the
scorer trustworthy as the selector's arithmetic: monotone in quality, monotone
in cost, funding-aware, pool-aware, cross-provider backup with an honest
warning, deterministic, and explainable term by term.
"""

from __future__ import annotations

import json
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
    # Opus leads Sol by half a coding-index point; with both pools fresh that lead
    # wins. Once the Claude pool is exhausted (list price) a routine task moves
    # to the funded Codex pool — the novel-hard case keeps weighing quality
    # more, which test_harder_tasks_weigh_cost_less pins.
    fresh = _rank(scoring.Task("coding", "low"), MAX_AND_PRO)
    assert fresh.primary is not None
    assert fresh.primary.model_id == "claude-opus-5"
    exhausted = _context(
        subs="| claude.ai Max ($200) | $200 | Anthropic | Claude Code |\n| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
        pools="| claude.ai Max — weekly | 7 days | `exhausted` | Tue 20:00 | overflow on |",
    )
    r = _rank(scoring.Task("coding", "low"), exhausted)
    assert r.primary is not None
    assert r.primary.provider == "openai"
    opus = next(c for c in r.candidates if c.model_id == "claude-opus-5")
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
