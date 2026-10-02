"""The Cost / Balanced / Quality ladder read off the operator's own frontier.

scoring.ladder computes the three picks in code: the cost/quality frontier
(list price vs AA Intelligence Index) over the models the user-context funds,
the points on it that meet the task's bar, and a rung for each posture.
recommend_structured_ladder puts the table of those ladders in the prompt, and
makes every rung the row's, whatever the engine writes.

The fixture catalog is tiny and hand-built so every pick can be worked out by
hand. Planning quality (the scorer's 0-100) is 0.7 x the AA Index min-max
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

import json
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


def _model(mid: str, name: str, inp: float, out: float, planning: str) -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
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
        _model("lite", "Lite", 0.1, 0.5, "C"),
        _model("luna", "Luna", 0.25, 1.25, "A"),
        _model("sonnet", "Sonnet", 2.0, 10.0, "S"),
        _model("sonnet-old", "Sonnet Old", 2.0, 10.0, "A"),
        _model("opus", "Opus", 4.0, 20.0, "S"),
        _model("astra", "Astra", 10.0, 50.0, "S"),
    ],
    "access_methods": [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "provider": "anthropic",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["sonnet", "sonnet-old", "opus"],
        },
        {
            "id": "codex-cli",
            "name": "Codex",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["lite", "luna", "astra"],
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


def test_rungs_converge_when_no_rung_can_differ() -> None:
    # Novel planning starts at the top effort a capped pool allows, so the
    # cheaper rung on Sonnet and the stronger on Opus are all that is left.
    picks = _picks(_ladder("planning", "high", novel=True))
    assert picks["cost"] == ("Sonnet", "xhigh")
    assert picks["balanced"] == ("Sonnet", "xhigh")
    assert picks["quality"] == ("Opus", "xhigh")


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
    assert {r.candidate.model_name for r in lad.rungs.values()} == {"Astra"}


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
    assert {r.candidate.model_name for r in lad.rungs.values()} == {"Luna"}


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
        "planning/high: COST = Sonnet @ Claude Code · high | BALANCED = Sonnet @ Claude Code · xhigh"
        " | QUALITY = Opus @ Claude Code · xhigh"
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
        on_frontier = {p.candidate.model_id for p in lad.frontier}
        assert all(r.candidate.model_id in on_frontier for r in lad.rungs.values())
