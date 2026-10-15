"""A recommendation names the latest version of a series.

The operator's rule (2026-10-14): never recommend GPT-6 Sol where GPT-6.1 Sol
runs, nor Opus 5 where Opus 5.5 does. A phase roadmap had put GPT-6 Sol on its
Medium Codex steps because the selector reads letters measured at each
model's top effort; the rule is not a benchmark judgment, so it holds even
where the older version scores higher. The fixture:

    model         $/1M in/out   HLE max   HLE medium   AA max   AA medium
    GPT-6 Sol       2 / 10        0.60       0.41       47.6      39.8
    GPT-6.1 Sol     2 / 10        0.50       0.50       51.8      47.8
    GPT-6 Luna    0.1 / 0.5       0.20        —         30.0       —
    Opus            4 / 20        0.61        —         57.6       —
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from roadmodel import scoring, series
from roadmodel.cli import cli

CATALOG_JSON = Path(__file__).resolve().parent.parent / "docs" / "catalog.json"


def _model(mid: str, name: str, inp: float, out: float, provider: str) -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
        "provider": provider,
        "input_price_per_1m": inp,
        "output_price_per_1m": out,
        "tier_cost": "low",
        "tiers": {
            cat: "A" for cat in ("coding", "planning", "agentic", "long-context", "knowledge")
        }
        | {"multimodal": "B", "speed": "B"},
        "jurisdiction": "us",
    }


CATALOG: dict[str, Any] = {
    "models": [
        _model("gpt-6-sol", "GPT-6 Sol", 2.0, 10.0, "openai"),
        _model("gpt-6.1-sol", "GPT-6.1 Sol", 2.0, 10.0, "openai"),
        _model("gpt-6-luna", "GPT-6 Luna", 0.1, 0.5, "openai"),
        _model("opus", "Opus", 4.0, 20.0, "anthropic"),
    ],
    "access_methods": [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "provider": "anthropic",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["opus"],
            "effort_levels": ["low", "medium", "high", "xhigh", "max"],
        },
        {
            "id": "codex-cli",
            "name": "Codex",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna"],
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


def _row(hle: float, aa: float, medium: tuple[float, float] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "aa_effort": "max",
        "evaluations": {"hle": hle, "artificial_analysis_intelligence_index": aa},
    }
    if medium is not None:
        row["effort_variants"] = {
            "medium": {
                "evaluations": {
                    "hle": medium[0],
                    "artificial_analysis_intelligence_index": medium[1],
                }
            }
        }
    return row


BENCH: dict[str, Any] = {
    "gpt-6-sol": _row(0.60, 47.6, (0.41, 39.8)),
    "gpt-6.1-sol": _row(0.50, 51.8, (0.50, 47.8)),
    "gpt-6-luna": {"evaluations": {"hle": 0.20, "artificial_analysis_intelligence_index": 30.0}},
    "opus": {"evaluations": {"hle": 0.61, "artificial_analysis_intelligence_index": 57.6}},
}

CONTEXT = """# User Context

## Active subscriptions

| Subscription | Monthly | Provider | What it pays for |
| --- | --- | --- | --- |
| claude.ai Max ($200) | $200 | Anthropic | Claude Code |
| ChatGPT Pro ($100) | $100 | OpenAI | Codex |

## Budget priority and speed posture

**Consumption headroom:** `capped`
"""

TASK = scoring.Task("knowledge", "medium")


def _successor(
    model: str = "GPT-6 Sol",
    effort: str = "Medium",
    catalog: dict[str, Any] = CATALOG,
    bench: dict[str, Any] = BENCH,
) -> scoring.Successor | None:
    return scoring.successor_for_pick(
        TASK, CONTEXT, model, effort, catalog=catalog, benchmarks=bench
    )


def test_a_newer_version_that_leads_where_the_step_runs_replaces_it() -> None:
    # At Medium, GPT-6.1 Sol leads GPT-6 Sol on HLE and the AA Index at the
    # same price, though GPT-6 Sol leads on HLE at max.
    got = _successor()
    assert got is not None
    assert got.candidate.model_id == "gpt-6.1-sol"
    assert got.replaces == "GPT-6 Sol"
    assert (got.effort, got.native) == ("medium", "medium")
    assert scoring.backup_cell(got) == "GPT-6.1 Sol — Codex · Intelligence Medium"


def test_the_latest_version_replaces_it_even_where_the_older_one_scores_higher() -> None:
    # At max GPT-6 Sol's HLE (0.60) is well above GPT-6.1 Sol's (0.50): the
    # rule is the operator's, not a benchmark judgment.
    got = _successor(effort="Max")
    assert got is not None and got.candidate.model_id == "gpt-6.1-sol"
    assert scoring.backup_cell(got) == "GPT-6.1 Sol — Codex · Intelligence Max"


def test_the_latest_version_replaces_it_whatever_it_costs() -> None:
    catalog = copy.deepcopy(CATALOG)
    catalog["models"][1]["output_price_per_1m"] = 12.0
    got = _successor(catalog=catalog)
    assert got is not None and got.candidate.model_id == "gpt-6.1-sol"


def test_a_benched_newer_version_keeps_the_older_one() -> None:
    got = scoring.successor_for_pick(
        TASK,
        CONTEXT,
        "GPT-6 Sol",
        "Medium",
        unavailable_models=["gpt-6.1-sol"],
        catalog=CATALOG,
        benchmarks=BENCH,
    )
    assert got is None


def test_a_newer_version_off_the_picks_platform_does_not_replace_it() -> None:
    catalog = copy.deepcopy(CATALOG)
    catalog["access_methods"][1]["supports_models"].remove("gpt-6.1-sol")
    assert _successor(catalog=catalog) is None


def test_the_newest_version_wins() -> None:
    catalog = copy.deepcopy(CATALOG)
    catalog["models"].append(_model("gpt-6.2-sol", "GPT-6.2 Sol", 2.0, 10.0, "openai"))
    catalog["access_methods"][1]["supports_models"].append("gpt-6.2-sol")
    bench = {**BENCH, "gpt-6.2-sol": _row(0.52, 52.0, (0.48, 46.0))}
    got = _successor(catalog=catalog, bench=bench)
    assert got is not None and got.candidate.model_id == "gpt-6.2-sol"


def test_another_series_or_the_newest_version_has_no_successor() -> None:
    assert _successor("GPT-6 Luna") is None
    assert _successor("GPT-6.1 Sol") is None


def test_rank_never_ranks_an_older_version_where_a_newer_one_runs() -> None:
    ranking = scoring.rank(TASK, CONTEXT, catalog=CATALOG, benchmarks=BENCH)
    assert "gpt-6-sol" not in {c.model_id for c in ranking.candidates}
    reasons = {e["model"]: e["reason"] for e in ranking.excluded}
    assert (
        reasons["gpt-6-sol"]
        == "a newer version (gpt-6.1-sol) runs on every platform that offers it"
    )
    # Asked for, it is still found (an old roadmap's step).
    older = scoring.rank(TASK, CONTEXT, catalog=CATALOG, benchmarks=BENCH, latest_only=False)
    assert "gpt-6-sol" in {c.model_id for c in older.candidates}


def test_an_older_version_stays_where_its_successor_is_not_offered() -> None:
    catalog = copy.deepcopy(CATALOG)
    catalog["access_methods"].append(
        {
            "id": "chatgpt-app",
            "name": "ChatGPT app",
            "provider": "openai",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["gpt-6-sol"],
        }
    )
    ranking = scoring.rank(TASK, CONTEXT, catalog=catalog, benchmarks=BENCH)
    sol = next(c for c in ranking.candidates if c.model_id == "gpt-6-sol")
    assert sol.platform_id == "chatgpt-app"


def test_a_benched_newer_version_keeps_the_older_one_ranked() -> None:
    ranking = scoring.rank(
        TASK, CONTEXT, unavailable_models=["gpt-6.1-sol"], catalog=CATALOG, benchmarks=BENCH
    )
    sol = next(c for c in ranking.candidates if c.model_id == "gpt-6-sol")
    assert sol.platform_id == "codex-cli"


@pytest.mark.parametrize(
    ("old", "new", "newer"),
    [
        ("gpt-6-sol", "gpt-6.1-sol", True),
        ("claude-opus-5", "claude-opus-5-5", True),
        ("opus-4.8", "claude-opus-5", True),
        ("gemini-2.5-flash", "gemini-3.8-flash", True),
        ("gpt-6.1-sol", "gpt-6-sol", False),
        ("gpt-6-sol", "gpt-6-luna", False),
        ("gpt-5.5", "gpt-5.5-mini", False),
        ("gpt-oss-20b", "gpt-oss-120b", False),
        ("gemini-3.1-flash-lite", "gemini-3.8-flash", False),
    ],
)
def test_series_and_version(old: str, new: str, newer: bool) -> None:
    assert series.is_newer(old, new) is newer


def test_supersede_mirrors_the_series_rule() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "update"))
    import supersede

    ids = [m["id"] for m in json.loads(CATALOG_JSON.read_text())["models"]]
    for a in ids:
        assert supersede._series(a) == series.series(a), a
        assert supersede._series_version(a) == series.version(a), a


def _cli(tmp_path: Path, monkeypatch: Any, *args: str) -> str:
    monkeypatch.setattr(scoring._cost, "_load_catalog", lambda: CATALOG)
    monkeypatch.setattr(scoring, "_load_benchmarks", lambda: BENCH)
    ctx = tmp_path / "user-context.md"
    ctx.write_text(CONTEXT, encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        ["backup", "--category", "knowledge", "--complexity", "medium", *args]
        + ["--user-context", str(ctx)],
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_backup_prints_the_successor_and_backs_it_up(tmp_path: Path, monkeypatch: Any) -> None:
    out = _cli(tmp_path, monkeypatch, "--model", "GPT-6 Sol", "--effort", "Medium")
    lines = out.splitlines()
    assert lines[0] == "MODEL    GPT-6.1 Sol — Codex · Intelligence Medium"
    assert "replaces GPT-6 Sol" in lines[1]
    assert lines[-1].startswith("BACKUP   Opus — Claude Code")
    payload = json.loads(
        _cli(
            tmp_path, monkeypatch, "--model", "GPT-6 Sol", "--effort", "Medium", "--output", "json"
        )
    )
    assert payload["model"]["model_id"] == "gpt-6.1-sol"
    assert payload["model"]["replaces"] == "GPT-6 Sol"
    assert payload["model_cell"] == "GPT-6.1 Sol — Codex · Intelligence Medium"
    assert payload["backup"]["model_id"] == "opus"


def test_backup_prints_no_model_line_without_a_successor(tmp_path: Path, monkeypatch: Any) -> None:
    out = _cli(tmp_path, monkeypatch, "--model", "GPT-6.1 Sol", "--effort", "Max")
    assert out.splitlines()[0].startswith("BACKUP   ")
    assert "MODEL" not in out
    payload = json.loads(
        _cli(tmp_path, monkeypatch, "--model", "GPT-6.1 Sol", "--effort", "Max", "--output", "json")
    )
    assert payload["model"] is None and payload["model_cell"] is None
