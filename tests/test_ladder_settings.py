"""A roadmap's Settings carry the full ladder, and engines see only the
latest version of each series.

The operator asked (2026-10-14) for roadmap Settings like /recommend's: Cost,
Balanced and Quality, each with its effort and a backup from another maker, so
a usage pool that turns `tight` or `exhausted` moves a step to another column
instead of the roadmap being refreshed. scoring.settings_ladder reads the
ladder with every pool at headroom and prints the table and its **Runs:**
line; `roadmodel ladder` and the MCP tool `roadmap_settings` serve it.

The fixture: Lite, Luna and Astra are one maker's (Codex), Sonnet and Opus
another's (Claude Code), as in tests/test_ladder_frontier.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from roadmodel import recommend, scoring
from roadmodel.cli import cli


def _model(
    mid: str, name: str, inp: float, out: float, letter: str, provider: str
) -> dict[str, Any]:
    cats = ("coding", "planning", "agentic", "long-context", "knowledge")
    return {
        "id": mid,
        "name": name,
        "provider": provider,
        "input_price_per_1m": inp,
        "output_price_per_1m": out,
        "tier_cost": "low",
        "tiers": {c: letter for c in cats} | {"multimodal": "B", "speed": "B"},
        "jurisdiction": "us",
    }


CATALOG: dict[str, Any] = {
    "models": [
        _model("lite", "Lite", 0.1, 0.5, "C", "openai"),
        _model("luna", "Luna", 0.25, 1.25, "A", "openai"),
        _model("sonnet", "Sonnet", 2.0, 10.0, "S", "anthropic"),
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
            "supports_models": ["sonnet", "opus"],
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
    for mid, aa in {"lite": 20, "luna": 40, "sonnet": 55, "opus": 58, "astra": 52}.items()
}


def _context(pool_state: str | None = None) -> str:
    text = """# User Context

## Active subscriptions

| Subscription | Monthly | Provider | What it pays for |
| --- | --- | --- | --- |
| claude.ai Max ($200) | $200 | Anthropic | Claude Code |
| ChatGPT Pro ($100) | $100 | OpenAI | Codex |

## Budget priority and speed posture

**Consumption headroom:** `capped`
"""
    if pool_state:
        text += f"""
## Usage-pool status

| Pool | Window | State | Resets | Notes |
| --- | --- | --- | --- | --- |
| claude.ai Max — weekly (all models) | 7 days | `{pool_state}` | Sun 2099-01-01 00:00 EDT | |
"""
    return text


PLANNING_MEDIUM = scoring.Task("planning", "medium")


def _settings(
    task: scoring.Task = PLANNING_MEDIUM, text: str | None = None, **kw: Any
) -> dict[str, Any]:
    got = scoring.settings_ladder(
        task, _context() if text is None else text, catalog=CATALOG, benchmarks=BENCH, **kw
    )
    assert got is not None
    return got


def test_the_table_carries_every_rung_with_its_effort_and_backup() -> None:
    lad = scoring.ladder(
        scoring.Task("planning", "medium"), _context(), catalog=CATALOG, benchmarks=BENCH
    )
    assert lad is not None
    got = _settings()
    for tier, rung in lad.rungs.items():
        col = got["columns"][tier]
        assert (col["model"], col["platform"]) == (
            rung.candidate.model_name,
            rung.candidate.platform_name,
        )
        assert rung.backup is not None and col["backup"] == scoring.backup_cell(rung.backup)
    lines = got["markdown"].splitlines()
    assert [c.strip() for c in lines[0].strip("|").split("|")] == [
        "Setting",
        "Cost",
        "Balanced",
        "Quality",
    ]
    assert [ln.split("|")[1].strip() for ln in lines[2:8]] == [
        "Model",
        "Backup",
        "Platform",
        "Effort",
        "Thinking",
        "Conversation",
    ]


def test_each_column_names_its_own_surfaces_dial() -> None:
    cols = _settings()["columns"]
    for col in cols.values():
        if col["platform_id"] == "codex-cli":
            assert col["effort_cell"].startswith("Intelligence ")
            assert col["thinking_cell"] == "—"
        else:
            assert col["effort_cell"].startswith("Effort ")
            assert col["thinking_cell"] == "On"


@pytest.mark.parametrize(
    ("budget", "runs"), [("cheap", "cost"), ("balanced", "balanced"), ("best", "quality")]
)
def test_the_step_runs_the_column_its_budget_priority_names(budget: str, runs: str) -> None:
    got = _settings(scoring.Task("planning", "medium", budget=budget))
    assert got["runs"] == runs
    assert got["markdown"].splitlines()[-1].startswith(f"**Runs:** {runs.capitalize()} — ")
    assert scoring.RUN_RULE in got["markdown"]


def test_a_phase_session_runs_quality_at_its_deepest_pinnable_rung() -> None:
    got = _settings(scoring.Task("planning", "high"), phase=True)
    assert got["runs"] == "quality"
    quality = got["columns"]["quality"]
    # Codex's dial goes to `ultra`, Claude Code's to `max`: a roadmap pins
    # neither ultra nor Ultracode.
    assert quality["effort"] == "max"
    assert "a phase-roadmap session runs Quality" in got["markdown"]


@pytest.mark.parametrize("state", ["tight", "exhausted"])
def test_the_table_outlives_a_pools_state(state: str) -> None:
    # The pool's state reaches the scorer …
    task = scoring.Task("planning", "medium")
    ranked = scoring.rank(task, _context(state), catalog=CATALOG, benchmarks=BENCH)
    assert {c.pool_state for c in ranked.candidates if c.provider == "anthropic"} == {state}
    neutral = scoring.rank(
        task, _context(state), catalog=CATALOG, benchmarks=BENCH, neutral_pools=True
    )
    assert {c.pool_state for c in neutral.candidates} == {"headroom"}
    # … but the roadmap's table is read as if every pool had headroom.
    assert _settings(task, _context(state)) == _settings(task, _context())


def _cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    monkeypatch.setattr(scoring._cost, "_load_catalog", lambda: CATALOG)
    monkeypatch.setattr(scoring, "_load_benchmarks", lambda: BENCH)
    ctx = tmp_path / "user-context.md"
    ctx.write_text(_context(), encoding="utf-8")
    result = CliRunner().invoke(cli, ["ladder", *args, "--user-context", str(ctx)])
    assert result.exit_code == 0, result.output
    return result.output


def test_ladder_prints_the_table_and_its_runs_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _cli(tmp_path, monkeypatch, "--category", "planning", "--complexity", "medium")
    assert out.startswith("| Setting ")
    assert "**Runs:** Balanced — " in out
    payload = json.loads(
        _cli(
            tmp_path,
            monkeypatch,
            "--category",
            "planning",
            "--complexity",
            "high",
            "--phase",
            "--output",
            "json",
        )
    )
    assert payload["runs"] == "quality" and set(payload["columns"]) == {
        "cost",
        "balanced",
        "quality",
    }


def _selector(models: list[str], methods: dict[str, list[str]]) -> str:
    els = "\n".join(f'<model id="{m}" name="{m}" input-price-per-1m="$1.00"/>' for m in models)
    meths = "\n".join(
        f'<method id="{mid}" name="{mid}" supports-models="{",".join(ids)}"/>'
        for mid, ids in methods.items()
    )
    return (
        f"<model-options>\n{els}\n</model-options>\n<access-methods>\n{meths}\n</access-methods>\n"
    )


def test_engines_see_only_the_latest_version_on_each_method() -> None:
    text = _selector(
        ["gpt-5.6-sol", "gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna"],
        {
            "codex-cli": ["gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna"],
            "chatgpt-app": ["gpt-5.6-sol", "gpt-6-sol"],
        },
    )
    out = recommend.selector_for_engine(text)
    assert 'id="codex-cli" name="codex-cli" supports-models="gpt-6.1-sol,gpt-6-luna"' in out
    # GPT-6 Sol stays where GPT-6.1 Sol is not offered, and displaces 5.6 there.
    assert 'id="chatgpt-app" name="chatgpt-app" supports-models="gpt-6-sol"' in out
    assert '<model id="gpt-5.6-sol"' not in out  # offered nowhere now
    assert '<model id="gpt-6-sol"' in out


def test_a_benched_newer_version_keeps_the_older_one_for_engines() -> None:
    text = _selector(["gpt-6-sol", "gpt-6.1-sol"], {"codex-cli": ["gpt-6-sol", "gpt-6.1-sol"]})
    out = recommend.selector_for_engine(text, ["gpt-6.1-sol"])
    assert 'supports-models="gpt-6-sol,gpt-6.1-sol"' in out
