"""The Cost / Balanced / Quality ladder read off the operator's own frontier.

scoring.ladder computes the three picks in code: the cost/quality frontier
(list price vs AA Intelligence Index) over the models the user-context funds,
the points on it that meet the task's bar, and a rung for each posture.
recommend_structured_ladder puts the table of those ladders in the prompt, and
makes every rung the row's, whatever the engine writes.

The fixture catalog is tiny and hand-built so every pick can be worked out by
hand. Lite, Luna and Astra are one maker's (Codex), Sonnet, Sonnet Old and Opus
another's (Claude Code). Planning quality (the scorer's 0-100) is 0.7 x the AA Index min-max
scaled over 20..58, plus 0.3 x the letter:

    model        blended $/1M   AA   planning   quality   frontier?
    Lite             0.20       20      C          9.0      yes
    Luna             0.50       40      A         57.9      yes
    Sonnet           4.00       55      S         91.5      yes
    Sonnet Old       4.00       38      A         54.2      no: Sonnet, same price
    Opus             8.00       58      S         97.0      yes
    Astra           20.00       52      S         85.9      no: Opus, for less
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from roadmodel import recommend as recommend_module
from roadmodel import scoring
from roadmodel.config import Config
from roadmodel.recommend import (
    _SAAS_LADDER_HEADER,
    _SAAS_LADDER_TABLE_HEADER,
    build_prompt,
    parse_classification,
    recommend_structured_ladder,
)


def _model(
    mid: str, name: str, inp: float, out: float, planning: str, provider: str
) -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
        "provider": provider,
        "input_price_per_1m": inp,
        "output_price_per_1m": out,
        "tier_cost": "low",
        "tiers": {
            "coding": planning,
            "planning": planning,
            "agentic": planning,
            "multimodal": "B",
            "long-context": planning,
            "knowledge": planning,
            "speed": "B",
        },
        "jurisdiction": "us",
    }


CATALOG: dict[str, Any] = {
    "models": [
        _model("lite", "Lite", 0.1, 0.5, "C", "openai"),
        _model("luna", "Luna", 0.25, 1.25, "A", "openai"),
        _model("sonnet", "Sonnet", 2.0, 10.0, "S", "anthropic"),
        _model("sonnet-old", "Sonnet Old", 2.0, 10.0, "A", "anthropic"),
        _model("opus", "Opus", 4.0, 20.0, "S", "anthropic"),
        _model("astra", "Astra", 10.0, 50.0, "S", "openai"),
    ],
    "access_methods": [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "provider": "anthropic",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["sonnet", "sonnet-old", "opus"],
            "effort_levels": ["low", "medium", "high", "xhigh", "max"],
        },
        {
            "id": "codex-cli",
            "name": "Codex",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["lite", "luna", "astra"],
            "effort_levels": ["low", "medium", "high", "xhigh", "max", "ultra"],
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

BENCH: dict[str, Any] = {
    mid: {"evaluations": {"artificial_analysis_intelligence_index": aa}}
    for mid, aa in {
        "lite": 20,
        "luna": 40,
        "sonnet": 55,
        "sonnet-old": 38,
        "opus": 58,
        "astra": 52,
    }.items()
}


def _context(subs: list[str], headroom: str = "capped") -> str:
    rows = "\n".join(subs)
    return f"""# User Context

## Active subscriptions

| Subscription | Monthly | Provider | What it pays for |
| --- | --- | --- | --- |
{rows}

## Budget priority and speed posture

**Consumption headroom:** `{headroom}`
"""


MAX = "| claude.ai Max ($200) | $200 | Anthropic | Claude Code |"
PRO = "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |"
BOTH = _context([MAX, PRO])


def _ladder(
    category: str, complexity: str, text: str = BOTH, novel: bool = False
) -> scoring.Ladder:
    lad = scoring.ladder(
        scoring.Task(category, complexity, novel), text, catalog=CATALOG, benchmarks=BENCH
    )
    assert lad is not None
    return lad


def _picks(lad: scoring.Ladder) -> dict[str, tuple[str, str]]:
    return {t: (r.candidate.model_name, r.effort) for t, r in lad.rungs.items()}


# --------------------------------------------------------------------------- #
# The frontier and the ladder
# --------------------------------------------------------------------------- #


def test_the_frontier_keeps_only_models_nothing_beats_for_less() -> None:
    names = [p.candidate.model_name for p in _ladder("planning", "medium").frontier]
    # Sonnet Old costs what Sonnet costs and scores lower; Astra costs more than
    # Opus and scores lower.
    assert names == ["Lite", "Luna", "Sonnet", "Opus"]


def test_three_adequate_points_give_three_models() -> None:
    # Medium needs 50 points: Lite (9) falls short, Luna (57.9) clears it.
    assert _picks(_ladder("planning", "medium")) == {
        "cost": ("Luna", "medium"),
        "balanced": ("Sonnet", "high"),
        "quality": ("Opus", "xhigh"),
    }


def test_two_adequate_points_separate_cost_and_balanced_by_effort() -> None:
    # High needs 70 points: only Sonnet and Opus clear it.
    assert _picks(_ladder("planning", "high")) == {
        "cost": ("Sonnet", "high"),
        "balanced": ("Sonnet", "xhigh"),
        "quality": ("Opus", "xhigh"),
    }


def test_a_lower_rung_on_the_same_model_runs_one_effort_below() -> None:
    # Novel planning starts every posture at the top effort a capped pool
    # allows (xhigh). COST and BALANCED both land on Sonnet, so COST steps one
    # level below BALANCED.
    assert _picks(_ladder("planning", "high", novel=True)) == {
        "cost": ("Sonnet", "high"),
        "balanced": ("Sonnet", "xhigh"),
        "quality": ("Opus", "xhigh"),
    }


def test_a_one_model_row_gets_three_distinct_efforts() -> None:
    # Claude Max alone, novel planning: only Opus (97.0) clears 85 once Sonnet
    # is benched, so every rung is Opus, each a level below the one above.
    lad = scoring.ladder(
        scoring.Task("planning", "high", True),
        _context([MAX]),
        unavailable_models=["sonnet"],
        catalog=CATALOG,
        benchmarks=BENCH,
    )
    assert lad is not None
    assert _picks(lad) == {
        "cost": ("Opus", "medium"),
        "balanced": ("Opus", "high"),
        "quality": ("Opus", "xhigh"),
    }


def test_at_the_dials_lowest_level_two_rungs_converge() -> None:
    # ChatGPT Pro without Astra, low-complexity planning: Luna alone clears
    # the bar. QUALITY runs it at medium, BALANCED one below at low, and COST
    # has no lower level to go to.
    lad = scoring.ladder(
        scoring.Task("planning", "low"),
        _context([PRO]),
        unavailable_models=["astra"],
        catalog=CATALOG,
        benchmarks=BENCH,
    )
    assert lad is not None
    assert _picks(lad) == {
        "cost": ("Luna", "low"),
        "balanced": ("Luna", "low"),
        "quality": ("Luna", "medium"),
    }


def test_on_a_free_path_two_rungs_on_one_model_converge() -> None:
    # `uncapped` on Claude Max: a lower effort saves this operator nothing, so
    # COST and BALANCED both run Sonnet at the top effort.
    picks = _picks(_ladder("planning", "high", _context([MAX], headroom="uncapped"), novel=True))
    assert picks == {
        "cost": ("Sonnet", "max"),
        "balanced": ("Sonnet", "max"),
        "quality": ("Opus", "max"),
    }


def test_a_dominated_model_is_never_a_rung() -> None:
    table = scoring.ladder_table(BOTH, catalog=CATALOG, benchmarks=BENCH)
    assert len(table) == len(scoring.table_keys())
    named = {r.candidate.model_name for lad in table.values() for r in lad.rungs.values()}
    assert "Sonnet Old" not in named
    assert "Astra" not in named


def test_the_pool_is_the_funded_models() -> None:
    lad = _ladder("planning", "medium", _context([MAX]))
    assert [p.candidate.model_name for p in lad.frontier] == ["Sonnet", "Opus"]
    assert all(r.candidate.platform_id == "claude-code" for r in lad.rungs.values())


def test_with_nothing_funded_the_whole_catalog_is_the_pool() -> None:
    lad = _ladder("planning", "medium", "")
    assert [p.candidate.model_name for p in lad.frontier] == ["Lite", "Luna", "Sonnet", "Opus"]


def test_one_point_over_the_bar_takes_every_rung() -> None:
    # ChatGPT Pro alone reaches Lite, Luna and Astra; without Opus in the pool
    # nothing beats Astra, and only Astra (85.9) clears novel work's 85.
    lad = _ladder("planning", "high", _context([PRO]), novel=True)
    assert [p.candidate.model_name for p in lad.frontier] == ["Lite", "Luna", "Astra"]
    assert _picks(lad) == {
        "cost": ("Astra", "medium"),
        "balanced": ("Astra", "high"),
        "quality": ("Astra", "xhigh"),
    }


def test_when_nothing_meets_the_bar_the_strongest_point_stands_alone() -> None:
    lad = scoring.ladder(
        scoring.Task("planning", "high", True),
        _context([PRO]),
        unavailable_models=["astra"],
        catalog=CATALOG,
        benchmarks=BENCH,
    )
    assert lad is not None
    assert lad.adequate == [lad.frontier[-1]]
    assert _picks(lad) == {
        "cost": ("Luna", "medium"),
        "balanced": ("Luna", "high"),
        "quality": ("Luna", "xhigh"),
    }


def test_uncapped_headroom_keeps_the_capability_steps_at_the_top_effort() -> None:
    picks = _picks(_ladder("planning", "medium", _context([MAX, PRO], headroom="uncapped")))
    assert picks == {
        "cost": ("Luna", "max"),
        "balanced": ("Sonnet", "max"),
        "quality": ("Opus", "max"),
    }


def test_the_table_renders_every_row_and_the_frontier() -> None:
    text = scoring.render_ladder_table(
        scoring.ladder_table(BOTH, catalog=CATALOG, benchmarks=BENCH)
    )
    assert text.startswith("<ladder-table>") and text.endswith("</ladder-table>")
    assert "Lite (AA 20, $0.20/1M list) < Luna" in text
    for category, complexity, novel in scoring.table_keys():
        assert f"\n{scoring.table_key(category, complexity, novel)}: COST = " in text
    assert (
        "planning/high: COST = Sonnet @ Claude Code · high, backup Astra @ Codex"
        " | BALANCED = Sonnet @ Claude Code · xhigh, backup Astra @ Codex"
        " | QUALITY = Opus @ Claude Code · xhigh, backup Astra @ Codex"
    ) in text


def test_ladder_round_trips_to_json() -> None:
    payload = _ladder("planning", "medium").to_dict()
    assert json.loads(json.dumps(payload))["rungs"]["quality"]["model_id"] == "opus"


# --------------------------------------------------------------------------- #
# The engine classifies; code holds the picks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("CLASSIFICATION: planning / high / routine", "planning/high"),
        ("CLASSIFICATION: Planning / High / Novel", "planning/high/novel"),
        ("  CLASSIFICATION: long context / medium / routine", "long-context/medium"),
        ("CLASSIFICATION: coding / medium / novel", "coding/medium"),
        ("CLASSIFICATION: knowledge / low", "knowledge/low"),
        ("CLASSIFICATION: cooking / low / routine", None),
        ("no classification at all", None),
    ],
)
def test_parse_classification(line: str, key: str | None) -> None:
    assert parse_classification(f"{line}\n\nTIER: QUALITY\n") == key


def test_the_table_header_and_table_go_into_the_prompt() -> None:
    system, _ = build_prompt(
        "t",
        user_context_text="ctx",
        ladder=True,
        ladder_table="<ladder-table>\nrow\n</ladder-table>",
    )
    assert system.startswith(_SAAS_LADDER_TABLE_HEADER)
    assert system.endswith("</ladder-table>")
    without, _ = build_prompt("t", user_context_text="ctx", ladder=True)
    assert without.startswith(_SAAS_LADDER_HEADER)
    assert "<ladder-table>" not in without


def test_novel_means_research_grade_work_only() -> None:
    # The engine flipped an ordinary planning task between routine and novel
    # run to run; the header now names what novel covers and what it never does.
    header = " ".join(_SAAS_LADDER_TABLE_HEADER.split())
    assert "`novel` marks research-grade work only" in header
    assert "an open problem, a new algorithm, or a proof of a result with no known proof" in header
    # A textbook proof (the keyless eval's math-proof probe, #917) read as
    # "a multi-step proof" by the letter and flipped the ladder to all-Opus.
    assert (
        "Writing out a known result (a textbook proof, a standard derivation) is `routine`"
        in header
    )
    assert "multi-step proof" not in header
    assert (
        "Planning, architecture, security hardening, design and refactors are `routine` "
        "at any difficulty"
    ) in header


@pytest.fixture
def table_on_fixture(monkeypatch: pytest.MonkeyPatch) -> dict[str, scoring.Ladder]:
    table = scoring.ladder_table(BOTH, catalog=CATALOG, benchmarks=BENCH)
    monkeypatch.setattr(recommend_module, "_ladder_table_for", lambda *_a, **_k: table)
    return table


def _config(tmp_path: Path) -> Config:
    ctx = tmp_path / "user-context.md"
    ctx.write_text(BOTH, encoding="utf-8")
    return Config(provider="anthropic", model=None, api_key="test-key", user_context_path=ctx)


def _block(
    model: str, platform: str, effort: str, classification: str | None = None
) -> dict[str, str]:
    base = {
        "model": model,
        "platform": platform,
        "effort": effort,
        "thinking": "On",
        "conversation": "New",
        "rationale": f"TASK: Planning a release. PICK: {model} fits. EFFORT: {effort} suits it.",
    }
    if classification:
        base["classification"] = classification
    return base


def _fake(blocks: dict[str, dict[str, str]]):
    seen: dict[str, Any] = {}

    def fake_ladder(*_args: object, **kwargs: object) -> dict[str, dict[str, str]]:
        seen.update(kwargs)
        return {tier: dict(block) for tier, block in blocks.items()}

    return fake_ladder, seen


def test_a_ladder_that_follows_its_row_is_healthy_even_on_one_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    fake, seen = _fake(
        {
            "quality": _block("Opus", "Claude Code", "XHigh", "planning/high"),
            "balanced": _block("Sonnet", "Claude Code", "XHigh", "planning/high"),
            "cost": _block("Sonnet", "Claude Code", "High", "planning/high"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))

    assert "<ladder-table>" in str(seen["ladder_table"])
    guard = result["guard"]
    assert guard["mode"] == "frontier"
    assert guard["classification"] == "planning/high"
    assert guard["found"] == "declared"
    assert guard["rewritten"] == []
    # Two rungs on Sonnet are the table's answer, not a collapse.
    assert guard["duplicate_models"] is True
    assert guard["healthy"] is True
    assert guard["frontier"] == ["Lite", "Luna", "Sonnet", "Opus"]
    assert result["picks"]["cost"]["settings"]["effort"] == "High"


def test_a_rung_that_leaves_its_row_is_rewritten_to_the_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    fake, _ = _fake(
        {
            "quality": _block("Opus", "Claude Code", "XHigh", "planning/high"),
            "balanced": _block("Sonnet", "Claude Code", "XHigh", "planning/high"),
            # The engine's own pick: the same price as Sonnet, and weaker.
            "cost": _block("Sonnet Old", "Claude Code", "Medium", "planning/high"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))

    assert result["guard"]["rewritten"] == ["cost"]
    cost_pick = result["picks"]["cost"]
    assert cost_pick["model"] == "Sonnet"
    assert cost_pick["settings"]["effort"] == "High"
    assert cost_pick["rationale"].startswith("TASK: Planning a release.")
    assert "cheapest model on your cost/quality frontier" in cost_pick["rationale"]
    assert cost_pick["rationale_sections"]["pick"].startswith("Sonnet is the cheapest")


def test_without_a_classification_the_matching_row_is_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    fake, _ = _fake(
        {
            "quality": _block("Opus", "Claude Code", "XHigh"),
            "balanced": _block("Sonnet", "Claude Code", "High"),
            "cost": _block("Luna", "Codex", "Medium"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    guard = recommend_structured_ladder("plan a release", _config(tmp_path))["guard"]
    assert guard["found"] == "matched"
    assert guard["rewritten"] == []
    assert guard["healthy"] is True


def test_a_response_the_table_cannot_place_keeps_the_old_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    fake, _ = _fake(
        {
            "quality": _block("Astra", "Codex", "XHigh"),
            "balanced": _block("Astra", "Codex", "High"),
            "cost": _block("Lite", "Codex", "Low"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    guard = recommend_structured_ladder("plan a release", _config(tmp_path))["guard"]
    assert guard["mode"] == "frontier"
    assert guard["classification"] is None
    assert guard["found"] == "unclassified"
    # The engine's own picks stand, judged as before: a repeated model is a collapse.
    assert guard["duplicate_models"] is True
    assert guard["healthy"] is False


def test_recommend_ladder_attaches_the_declared_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = "CLASSIFICATION: planning / high / routine\n\n" + "\n\n".join(
        f"TIER: {tier}\nMODEL: {model}\nPLATFORM: Claude Code\nEFFORT: High\nTHINKING: On\n"
        f"CONVERSATION: New\nRATIONALE: TASK: t. PICK: p. EFFORT: e."
        for tier, model in (("QUALITY", "Opus"), ("BALANCED", "Sonnet"), ("COST", "Sonnet"))
    )
    prompts: dict[str, str] = {}

    class FakeAdapter:
        def recommend(self, user_prompt: str, system_prompt: str, **_kw: object) -> str:
            prompts["system"] = system_prompt
            return raw

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", FakeAdapter())
    table_text = "<ladder-table>\nplanning/high: ...\n</ladder-table>"
    parsed = recommend_module.recommend_ladder(
        "plan a release", _config(tmp_path), user_context_text=BOTH, ladder_table=table_text
    )
    assert {b["classification"] for b in parsed.values()} == {"planning/high"}
    assert prompts["system"].endswith(table_text)
    # Without a table the line is not read: the free-choice ladder has no rows.
    parsed = recommend_module.recommend_ladder(
        "plan a release", _config(tmp_path), user_context_text=BOTH
    )
    assert all("classification" not in b for b in parsed.values())


def test_the_real_catalog_and_user_context_example_yield_a_full_table() -> None:
    example = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "roadmodel"
        / "data"
        / "user-context.example.md"
    )
    table = scoring.ladder_table(example.read_text(encoding="utf-8"))
    assert len(table) == len(scoring.table_keys())
    for lad in table.values():
        prices = [lad.rungs[t].point.price_usd for t in scoring.LADDER_TIERS]
        assert prices == sorted(prices), "COST <= BALANCED <= QUALITY in price"
        # The picks are read off the frontier over each model at its measured
        # efforts; a category specialist is the one pick that may stand off it.
        on_frontier = {p.candidate.model_id for p in lad.points}
        assert all(r.candidate.model_id in on_frontier or r.specialist for r in lad.rungs.values())
    # Claude Max + ChatGPT Pro, no Google plan: Opus 5.5 tops the multimodal
    # frontier at an A, and Fable 5.1 (S for multimodal) takes QUALITY.
    quality = table["multimodal/medium"].rungs["quality"]
    assert quality.specialist and quality.candidate.model_id == "claude-fable-5.1"


def test_on_claude_code_the_rows_effort_is_set_when_the_engine_copies_only_the_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    # Seen in production: the engine copied Sonnet onto COST but at BALANCED's
    # XHigh, so the two rungs read the same.
    fake, _ = _fake(
        {
            "quality": _block("Opus", "Claude Code", "Ultracode", "planning/high"),
            "balanced": _block("Sonnet", "Claude Code", "Extra high", "planning/high"),
            "cost": _block("Sonnet", "Claude Code", "XHigh", "planning/high"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))

    guard = result["guard"]
    assert guard["rewritten"] == []
    # "Extra high" is XHigh; Ultracode on QUALITY is above the row's XHigh, so
    # it is set back to the row's level too.
    assert guard["effort_set"] == ["quality", "cost"]
    assert result["picks"]["cost"]["settings"]["effort"] == "High"
    assert result["picks"]["balanced"]["settings"]["effort"] == "Extra high"
    assert result["picks"]["quality"]["settings"]["effort"] == "XHigh"
    cost_sections = result["picks"]["cost"]["rationale_sections"]
    assert cost_sections["pick"] == "Sonnet fits."
    assert cost_sections["effort"].startswith("High is the effort the cheap posture sets")


def test_ultracode_stands_where_the_row_says_max(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uncapped = _context([MAX, PRO], headroom="uncapped")
    table = scoring.ladder_table(uncapped, catalog=CATALOG, benchmarks=BENCH)
    monkeypatch.setattr(recommend_module, "_ladder_table_for", lambda *_a, **_k: table)
    fake, _ = _fake(
        {
            "quality": _block("Opus", "Claude Code", "Ultracode", "planning/medium"),
            "balanced": _block("Sonnet", "Claude Code", "Max", "planning/medium"),
            "cost": _block("Luna", "Codex", "High", "planning/medium"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))
    # Codex documents its dial too, so its row's max is set there; Ultracode
    # stands on Claude Code alone.
    assert result["guard"]["effort_set"] == ["cost"]
    assert result["picks"]["quality"]["settings"]["effort"] == "Ultracode"
    assert result["picks"]["cost"]["settings"]["intelligence"] == "Max"


# --------------------------------------------------------------------------- #
# Native effort levels: each surface's own dial, from the catalog
# --------------------------------------------------------------------------- #


def _with_levels(method_id: str, **fields: Any) -> dict[str, Any]:
    """CATALOG with one access method's effort fields replaced (a field set
    to None is removed)."""
    cat = copy.deepcopy(CATALOG)
    method = next(m for m in cat["access_methods"] if m["id"] == method_id)
    for key, value in fields.items():
        if value is None:
            method.pop(key, None)
        else:
            method[key] = value
    return cat


# Gemini's dial for one model, documented per model: low / medium / high.
GEMINI_LIKE = _with_levels(
    "codex-cli",
    effort_levels=["minimal", "low", "medium", "high"],
    effort_levels_by_model={"astra": ["low", "medium", "high"], "luna": ["minimal", "high"]},
)


@pytest.mark.parametrize(
    ("platform", "model", "level", "native"),
    [
        ("claude-code", "opus", "xhigh", "xhigh"),
        ("claude-code", "opus", "Extra high", "xhigh"),
        ("claude-code", "sonnet", "max", "max"),
        ("codex-cli", "astra", "medium", "medium"),
        # No xhigh or max on the dial: the highest level below it.
        ("codex-cli", "astra", "xhigh", "high"),
        ("codex-cli", "astra", "max", "high"),
        # medium is missing too; minimal sits below low.
        ("codex-cli", "luna", "medium", "minimal"),
        ("codex-cli", "luna", "low", "minimal"),
        # The docs distinguish models and leave this one out: no dial.
        ("codex-cli", "lite", "high", None),
        ("no-such-surface", "opus", "high", None),
    ],
)
def test_native_level(platform: str, model: str, level: str, native: str | None) -> None:
    assert scoring.native_level(platform, model, level, catalog=GEMINI_LIKE) == native


def test_below_the_lowest_native_level_the_lowest_stands() -> None:
    cat = _with_levels("codex-cli", effort_levels=["high", "max"])
    assert scoring.native_level("codex-cli", "luna", "low", catalog=cat) == "high"


def test_a_surface_without_documented_levels_has_no_native_level() -> None:
    cat = _with_levels("codex-cli", effort_levels=None)
    assert scoring.native_level("codex-cli", "luna", "high", catalog=cat) is None
    lad = scoring.ladder(scoring.Task("planning", "medium"), BOTH, catalog=cat, benchmarks=BENCH)
    assert lad is not None
    assert lad.rungs["cost"].native is None
    assert lad.rungs["cost"].level == "medium"


def test_two_scorer_levels_on_one_native_level_are_told_apart_natively() -> None:
    # ChatGPT Pro alone, novel planning: Astra takes every rung. The scorer
    # asks xhigh of all three, which this dial reads as high, so BALANCED steps
    # to medium and COST to low on the dial itself.
    lad = scoring.ladder(
        scoring.Task("planning", "high", True),
        _context([PRO]),
        catalog=GEMINI_LIKE,
        benchmarks=BENCH,
    )
    assert lad is not None
    assert {t: (r.candidate.model_name, r.native) for t, r in lad.rungs.items()} == {
        "cost": ("Astra", "low"),
        "balanced": ("Astra", "medium"),
        "quality": ("Astra", "high"),
    }
    text = scoring.render_ladder_table({"planning/high/novel": lad})
    assert (
        "planning/high/novel: COST = Astra @ Codex · low | BALANCED = Astra @ Codex · medium"
        " | QUALITY = Astra @ Codex · high"
    ) in text
    # ChatGPT Pro alone: no other maker, so no backup.
    assert "backup" not in text.split("\n")[-2]
    assert lad.to_dict()["rungs"]["quality"]["native_effort"] == "high"


def test_every_documented_dial_gets_the_rows_level_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    table = scoring.ladder_table(_context([PRO]), catalog=GEMINI_LIKE, benchmarks=BENCH)
    monkeypatch.setattr(recommend_module, "_ladder_table_for", lambda *_a, **_k: table)
    fake, _ = _fake(
        {
            "quality": _block("Astra", "Codex", "XHigh", "planning/high/novel"),
            "balanced": _block("Astra", "Codex", "XHigh", "planning/high/novel"),
            "cost": _block("Astra", "Codex", "Low", "planning/high/novel"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))
    assert result["guard"]["effort_set"] == ["quality", "balanced"]
    assert {t: p["settings"] for t, p in result["picks"].items()} == {
        "quality": {"intelligence": "High"},
        "balanced": {"intelligence": "Medium"},
        "cost": {"intelligence": "Low"},
    }


def test_a_surface_without_documented_levels_keeps_the_engines_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cat = _with_levels("codex-cli", effort_levels=None)
    table = scoring.ladder_table(BOTH, catalog=cat, benchmarks=BENCH)
    monkeypatch.setattr(recommend_module, "_ladder_table_for", lambda *_a, **_k: table)
    fake, _ = _fake(
        {
            "quality": _block("Opus", "Claude Code", "XHigh", "planning/medium"),
            "balanced": _block("Sonnet", "Claude Code", "High", "planning/medium"),
            "cost": _block("Luna", "Codex", "High", "planning/medium"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))
    assert result["guard"]["effort_set"] == []
    assert result["picks"]["cost"]["settings"]["intelligence"] == "High"


# --------------------------------------------------------------------------- #
# Backups: the other makers' frontier, at no higher list price
# --------------------------------------------------------------------------- #


def _backups(lad: scoring.Ladder) -> dict[str, tuple[str, str, str] | None]:
    return {
        t: (r.backup.candidate.model_name, r.backup.candidate.platform_name, r.backup.level)
        if r.backup
        else None
        for t, r in lad.rungs.items()
    }


def test_each_rung_backs_up_to_the_other_makers_best_at_no_higher_price() -> None:
    # Medium planning needs 50. Codex's frontier is Lite, Luna, Astra, of which
    # Luna (57.9) and Astra (85.9) clear it: Sonnet ($4) and Opus ($8) back up
    # to Luna, the dearest at or below their price. Nothing on Claude Code's
    # frontier (Sonnet, Opus) costs Luna's $0.50 or less, so Luna backs up to
    # the cheapest adequate point above it, Sonnet. Each runs at its rung's
    # posture's effort on its own dial.
    lad = _ladder("planning", "medium")
    assert _backups(lad) == {
        "cost": ("Sonnet", "Claude Code", "medium"),
        "balanced": ("Luna", "Codex", "high"),
        "quality": ("Luna", "Codex", "xhigh"),
    }
    assert lad.backup_warning is None


def test_a_backup_above_the_rungs_price_only_when_nothing_cheaper_clears_the_bar() -> None:
    # High planning needs 70: only Astra ($20) clears it on Codex's frontier.
    lad = _ladder("planning", "high")
    assert {b[0] for b in _backups(lad).values() if b} == {"Astra"}


def test_with_no_adequate_backup_the_strongest_other_maker_point_stands() -> None:
    # Novel planning needs 85; with Astra benched, Codex's frontier is Lite and
    # Luna, and neither clears it: Luna is the stronger.
    lad = scoring.ladder(
        scoring.Task("planning", "high", True),
        BOTH,
        unavailable_models=["astra"],
        catalog=CATALOG,
        benchmarks=BENCH,
    )
    assert lad is not None
    assert {b[0] for b in _backups(lad).values() if b} == {"Luna"}


def test_with_one_maker_funded_there_is_no_backup_and_a_warning_says_why() -> None:
    lad = _ladder("planning", "medium", _context([MAX]))
    assert _backups(lad) == {"cost": None, "balanced": None, "quality": None}
    assert lad.backup_warning is not None and "anthropic only" in lad.backup_warning


def test_the_table_and_json_carry_each_rungs_backup() -> None:
    lad = _ladder("planning", "medium")
    text = scoring.render_ladder_table({"planning/medium": lad})
    assert (
        "planning/medium: COST = Luna @ Codex · medium, backup Sonnet @ Claude Code | "
        "BALANCED = Sonnet @ Claude Code · high, backup Luna @ Codex | "
        "QUALITY = Opus @ Claude Code · xhigh, backup Luna @ Codex"
    ) in text
    payload = json.loads(json.dumps(lad.to_dict()))
    assert payload["rungs"]["cost"]["backup"]["model_id"] == "sonnet"
    assert payload["rungs"]["cost"]["backup"]["native_effort"] == "medium"


def test_a_backup_that_differs_from_the_row_is_replaced_and_planned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_on_fixture: dict[str, scoring.Ladder]
) -> None:
    blocks = {
        "quality": _block("Opus", "Claude Code", "XHigh", "planning/medium"),
        "balanced": _block("Sonnet", "Claude Code", "High", "planning/medium"),
        "cost": _block("Luna", "Codex", "Medium", "planning/medium"),
    }
    blocks["quality"]["backup"] = "Astra"  # off this rung's price: Luna is the row's
    blocks["balanced"]["backup"] = "Luna"  # the row's already
    blocks["cost"]["backup"] = "Opus"  # dearer than the row's Sonnet
    fake, _ = _fake(blocks)
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("plan a release", _config(tmp_path))

    assert result["guard"]["backup_set"] == ["quality", "cost"]
    picks = result["picks"]
    assert {t: p["backup"] for t, p in picks.items()} == {
        "quality": "Luna",
        "balanced": "Luna",
        "cost": "Sonnet",
    }
    assert picks["cost"]["backup_plan"] == {
        "model": "Sonnet",
        "platform": "Claude Code",
        "effort": "Medium",
    }
    assert picks["quality"]["backup_plan"]["effort"] == "XHigh"


def test_the_header_says_to_copy_the_rows_backup() -> None:
    header = " ".join(_SAAS_LADDER_TABLE_HEADER.split())
    assert "BACKUP is the model the row names after `backup`" in header


# --------------------------------------------------------------------------- #
# A category specialist may take QUALITY (every category but planning)
# --------------------------------------------------------------------------- #


def _specialist_catalog() -> dict[str, Any]:
    # Astra rates S for multimodal (the fixture's others rate B). Multimodal
    # has no AA evidence, so quality is the letter: S 90, B 50.
    cat = copy.deepcopy(CATALOG)
    next(m for m in cat["models"] if m["id"] == "astra")["tiers"]["multimodal"] = "S"
    return cat


def test_a_category_specialist_takes_quality_and_the_frontier_keeps_the_rest() -> None:
    # Medium multimodal needs 50 in the category, which every frontier point
    # meets at B, and 50 in general capability (planning quality), which Lite
    # (9.0) misses; the strongest adequate point is Opus (B, 50). Astra sits
    # off the frontier (Opus beats it on the AA Index for less) and rates S
    # (90): it takes QUALITY at the best posture's effort. COST is the cheapest
    # adequate point, Luna. Every frontier point rates the same B for
    # multimodal, so none above Luna adds anything in the category: BALANCED
    # runs Luna at the balanced effort.
    lad = scoring.ladder(
        scoring.Task("multimodal", "medium"), BOTH, catalog=_specialist_catalog(), benchmarks=BENCH
    )
    assert lad is not None
    assert _picks(lad) == {
        "cost": ("Luna", "low"),
        "balanced": ("Luna", "medium"),
        "quality": ("Astra", "high"),
    }
    assert lad.rungs["quality"].specialist is True
    assert not lad.rungs["cost"].specialist and not lad.rungs["balanced"].specialist
    assert lad.to_dict()["rungs"]["quality"]["specialist"] is True
    text = scoring.render_ladder_table({"multimodal/medium": lad})
    assert "QUALITY = Astra @ Codex · high (top for multimodal work)" in text


def test_a_specialist_needs_both_a_higher_letter_and_higher_quality() -> None:
    # Astra at A (70) still beats Opus's B (50); at B it ties the letter.
    cat = _specialist_catalog()
    astra = next(m for m in cat["models"] if m["id"] == "astra")
    astra["tiers"]["multimodal"] = "B"
    lad = scoring.ladder(scoring.Task("multimodal", "medium"), BOTH, catalog=cat, benchmarks=BENCH)
    assert lad is not None
    assert not lad.rungs["quality"].specialist
    assert lad.rungs["quality"].candidate.model_name == "Opus"


def test_planning_has_no_specialist() -> None:
    # Planning's evidence is the AA Index itself: the frontier already ranks it.
    assert "planning" not in scoring.SPECIALIST_CATEGORIES
    assert scoring.SPECIALIST_CATEGORIES == set(scoring.CATEGORIES) - {"planning"}
    lad = _ladder("planning", "medium")
    top = lad.rungs["quality"].point
    stronger = replace(
        next(p.candidate for p in lad.frontier if p.candidate.model_id == "lite"),
        model_id="ghost",
        letter="S",
        quality=top.candidate.quality + 10,
        requirement_penalty=0.0,
    )
    ranking_pool = [p.candidate for p in lad.frontier] + [stronger]
    for category, expected in (("planning", None), ("knowledge", "ghost")):
        task = scoring.Task(category, "medium")
        top_a = replace(top, candidate=replace(top.candidate, letter="A"))
        got = scoring._specialist(task, ranking_pool, lad.frontier, top_a, BENCH)
        assert (got.candidate.model_id if got else None) == expected


def test_the_quality_pick_carries_the_specialist_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    table = scoring.ladder_table(BOTH, catalog=_specialist_catalog(), benchmarks=BENCH)
    monkeypatch.setattr(recommend_module, "_ladder_table_for", lambda *_a, **_k: table)
    fake, _ = _fake(
        {
            # The engine names the frontier's top; code holds the row's specialist.
            "quality": _block("Opus", "Claude Code", "High", "multimodal/medium"),
            "balanced": _block("Luna", "Codex", "Medium", "multimodal/medium"),
            "cost": _block("Luna", "Codex", "Low", "multimodal/medium"),
        }
    )
    monkeypatch.setattr(recommend_module, "recommend_ladder", fake)
    result = recommend_structured_ladder("read this chart", _config(tmp_path))
    guard = result["guard"]
    assert guard["rewritten"] == ["quality"]
    assert guard["specialist"] == {"tier": "quality", "category": "multimodal"}
    quality = result["picks"]["quality"]
    assert quality["model"] == "Astra"
    assert quality["specialist"] is True
    assert quality["specialist_category"] == "multimodal"
    assert "strongest model you can run for multimodal work" in quality["rationale"]
    assert "specialist" not in result["picks"]["cost"]


# --------------------------------------------------------------------------- #
# Calibration: BALANCED beats COST in the category; COST is already paid for
# --------------------------------------------------------------------------- #


def test_balanced_must_beat_cost_in_the_tasks_category() -> None:
    # Long-context letters make Luna (S) stronger than Sonnet (A), which costs
    # eight times more: on the AA-Index frontier Sonnet sits between COST
    # (Luna) and QUALITY (Opus), but it buys less long-context quality than
    # COST already gives. BALANCED runs Luna at the balanced effort instead.
    cat = copy.deepcopy(CATALOG)
    letters = {"lite": "C", "luna": "S", "sonnet": "A", "opus": "S"}
    for m in cat["models"]:
        if m["id"] in letters:
            m["tiers"]["long-context"] = letters[m["id"]]
    lad = scoring.ladder(
        scoring.Task("long-context", "medium"), BOTH, catalog=cat, benchmarks=BENCH
    )
    assert lad is not None
    picks = _picks(lad)
    assert picks["cost"][0] == "Luna"
    assert picks["balanced"][0] == "Luna"
    assert picks["quality"][0] == "Opus"
    assert picks["balanced"] != picks["cost"]


def _with_per_token_muse() -> dict[str, Any]:
    # Muse: cheaper than Sonnet, on the AA-Index frontier, reachable only per
    # token through an aggregator key.
    cat = copy.deepcopy(CATALOG)
    cat["models"].append(_model("muse", "Muse", 0.5, 2.5, "S", "meta"))
    cat["access_methods"].append(
        {
            "id": "openrouter",
            "name": "OpenRouter",
            "provider": "openrouter",
            "provider_jurisdiction": "us",
            "billing": "per-token",
            "supports_models": ["muse"],
        }
    )
    return cat


MUSE_BENCH: dict[str, Any] = {
    **BENCH,
    "muse": {"evaluations": {"artificial_analysis_intelligence_index": 45}},
}
OPENROUTER_KEY = (
    "\n## Active API keys\n\n| Provider | Key present | Notes |\n| --- | --- | --- |\n"
    "| OpenRouter | Yes | aggregator |\n"
)


def test_cost_prefers_a_prepaid_pool_over_a_per_token_call() -> None:
    # High planning needs 70: Muse, Sonnet and Opus clear it, and Muse is the
    # cheapest by list price. Sonnet runs on a subscription already paid for,
    # so it takes COST; a Muse call would be fresh spend.
    cat = _with_per_token_muse()
    lad = scoring.ladder(
        scoring.Task("planning", "high"),
        BOTH + OPENROUTER_KEY,
        catalog=cat,
        benchmarks=MUSE_BENCH,
    )
    assert lad is not None
    assert "Muse" in [p.candidate.model_name for p in lad.adequate]
    assert lad.rungs["cost"].candidate.model_name == "Sonnet"
    assert lad.rungs["cost"].candidate.funding == "subscription"


def test_a_per_token_point_takes_cost_when_nothing_prepaid_is_adequate() -> None:
    cat = _with_per_token_muse()
    lad = scoring.ladder(
        scoring.Task("planning", "high"),
        _context([]) + OPENROUTER_KEY,
        catalog=cat,
        benchmarks=MUSE_BENCH,
    )
    assert lad is not None
    assert lad.rungs["cost"].candidate.model_name == "Muse"


def test_speed_never_ranks_local_weights() -> None:
    # Speed evidence is hosted throughput; a model on the operator's own
    # machine runs at its own pace, so the local method drops out for speed
    # and stays in for every other category.
    cat = copy.deepcopy(CATALOG)
    cat["access_methods"].append(
        {
            "id": "ollama",
            "name": "Ollama (local)",
            "provider": "ollama",
            "provider_jurisdiction": "local",
            "billing": "local",
            "supports_models": ["lite"],
        }
    )
    text = BOTH + (
        "\n## Local models (Ollama)\n\n| Runtime | Present |\n| --- | --- |\n"
        "| Ollama installed | Yes |\n\n"
        "| Catalog model id | Ollama tag |\n| --- | --- |\n| lite | lite:latest |\n"
    )

    def lite_platform(category: str) -> str:
        r = scoring.rank(scoring.Task(category, "low"), text, catalog=cat, benchmarks=BENCH)
        return next(c.platform_id for c in r.candidates if c.model_id == "lite")

    assert lite_platform("coding") == "ollama"
    assert lite_platform("speed") == "codex-cli"


def test_balanced_prefers_a_prepaid_point_over_a_per_token_one() -> None:
    # Medium planning: COST is Luna. A cheap, strong Muse (per token, AA 54)
    # and Sonnet (prepaid) both sit between Luna and Opus and both beat Luna;
    # Muse has the better balanced score, but BALANCED takes Sonnet, the one
    # already paid for.
    cat = _with_per_token_muse()
    muse = next(m for m in cat["models"] if m["id"] == "muse")
    muse["input_price_per_1m"], muse["output_price_per_1m"] = 0.3, 1.5
    bench = {**BENCH, "muse": {"evaluations": {"artificial_analysis_intelligence_index": 54}}}
    lad = scoring.ladder(
        scoring.Task("planning", "medium"),
        BOTH + OPENROUTER_KEY,
        catalog=cat,
        benchmarks=bench,
    )
    assert lad is not None
    between = [p.candidate.model_name for p in lad.adequate][1:-1]
    assert "Muse" in between and "Sonnet" in between
    scores = {p.candidate.model_name: p.candidate.score for p in lad.adequate}
    assert scores["Muse"] > scores["Sonnet"]
    assert lad.rungs["cost"].candidate.model_name == "Luna"
    assert lad.rungs["balanced"].candidate.model_name == "Sonnet"


# --------------------------------------------------------------------------- #
# Effort-aware evidence: a pick is credited with what AA measured it at the
# effort it runs
# --------------------------------------------------------------------------- #

# Luna as AA measures it at each effort (its headline row is the max one).
# Planning quality, with the scale still drawn over the headline rows (20..58)
# and Luna's A letter (21 points): low 21.0, medium 35.7, high 44.9, xhigh
# 50.5, max 57.9. A capped pool runs planning/medium at most at xhigh.
_LUNA_LEVELS = {"low": 20, "medium": 28, "high": 33, "xhigh": 36}


def _bench_with_levels(**extra: dict[str, Any]) -> dict[str, Any]:
    bench = copy.deepcopy(BENCH)
    bench["luna"]["aa_effort"] = "max"
    bench["luna"]["effort_variants"] = {
        level: {"evaluations": {"artificial_analysis_intelligence_index": aa}}
        for level, aa in _LUNA_LEVELS.items()
    }
    for mid, fields in extra.items():
        bench[mid].update(fields)
    return bench


def test_a_pick_runs_at_the_effort_whose_measured_score_clears_the_bar() -> None:
    # Medium planning needs 50. Luna's headline (max, 57.9) clears it, but a
    # capped pool never runs max; of the efforts it may run, only xhigh (50.5)
    # clears the bar, so COST is Luna at xhigh, where it used to be credited
    # its max score and run at medium.
    lad = scoring.ladder(
        scoring.Task("planning", "medium"), BOTH, catalog=CATALOG, benchmarks=_bench_with_levels()
    )
    assert lad is not None
    assert _picks(lad) == {
        "cost": ("Luna", "xhigh"),
        "balanced": ("Sonnet", "high"),
        "quality": ("Opus", "xhigh"),
    }
    cost = lad.rungs["cost"]
    assert cost.candidate.evidence_level == "xhigh"
    assert cost.point.aa_index == 36
    # Each effort is its own point, priced by its token multiplier; Luna at
    # low (20 for 0.30) adds nothing over Lite (20 for 0.20).
    assert [
        (p.candidate.model_name, p.candidate.evidence_level, p.price_usd) for p in lad.points
    ] == [
        ("Lite", None, 0.2),
        ("Luna", "medium", 0.4),
        ("Luna", "high", 0.5),
        ("Luna", "xhigh", 0.8),
        ("Sonnet", None, 4.0),
        ("Opus", None, 8.0),
    ]
    # The models' frontier, as /models draws it, is unchanged.
    assert [p.candidate.model_name for p in lad.frontier] == ["Lite", "Luna", "Sonnet", "Opus"]
    assert lad.to_dict()["rungs"]["cost"]["evidence_level"] == "xhigh"


def test_a_model_measured_only_at_efforts_the_task_does_not_run_is_left_out() -> None:
    # AA measured Sonnet at max alone; a capped pool runs medium planning at
    # most at xhigh, so nothing says how Sonnet does there. Without it, Sonnet
    # Old (38, planning 54.2) is the best model at its price and stands
    # between COST and QUALITY.
    lad = scoring.ladder(
        scoring.Task("planning", "medium"),
        BOTH,
        catalog=CATALOG,
        benchmarks=_bench_with_levels(sonnet={"aa_effort": "max"}),
    )
    assert lad is not None
    assert "sonnet" not in {p.candidate.model_id for p in lad.points}
    assert _picks(lad) == {
        "cost": ("Luna", "xhigh"),
        "balanced": ("Sonnet Old", "high"),
        "quality": ("Opus", "xhigh"),
    }


def test_a_hard_task_needs_general_capability_as_well_as_the_category() -> None:
    # Lite rates S for long-context (90 points: the fixture has no LCR
    # figures) but scores 9 in general capability, the AA Index measure that
    # planning reads. Medium work needs 50 in both, so Luna takes COST.
    cat = copy.deepcopy(CATALOG)
    next(m for m in cat["models"] if m["id"] == "lite")["tiers"]["long-context"] = "S"
    lad = scoring.ladder(
        scoring.Task("long-context", "medium"), BOTH, catalog=cat, benchmarks=BENCH
    )
    assert lad is not None
    lite = next(p.candidate for p in lad.points if p.candidate.model_id == "lite")
    assert lite.quality == 90.0 and lite.requirement_penalty > 0
    assert lad.rungs["cost"].candidate.model_name == "Luna"


def test_with_composites_scores_each_effort_among_the_headline_rows() -> None:
    bench = {
        "a": {"evaluations": {"scicode": 10, "terminalbench_v4_0": 10}},
        "b": {"evaluations": {"scicode": 20, "terminalbench_v4_0": 20}},
        "c": {
            "evaluations": {"scicode": 30, "terminalbench_v4_0": 30},
            "effort_variants": {"low": {"evaluations": {"scicode": 15, "terminalbench_v4_0": 25}}},
        },
    }
    before = copy.deepcopy(bench)
    out = scoring.with_composites(bench)
    assert out["c"]["evaluations"]["coding_composite"] == 1.0
    # 15 sits above one of three headline rows, 25 above two: (1/3 + 2/3) / 2.
    assert out["c"]["effort_variants"]["low"]["evaluations"]["coding_composite"] == pytest.approx(
        0.5
    )
    assert bench == before, "the caller's rows are not modified"
    assert scoring.measured_levels(out, "c") == {"low": out["c"]["effort_variants"]["low"]}
    assert scoring._evidence(out, "c", "scicode", "low") == 15
    assert scoring._evidence(out, "c", "scicode", "high") is None
    assert scoring._evidence(out, "c", "scicode") == 30
