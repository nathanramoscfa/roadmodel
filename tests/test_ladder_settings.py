"""A roadmap's Settings carry the full ladder, and engines see only the
latest version of each series.

The operator asked (2026-10-14) for roadmap Settings like /recommend's: Cost,
Balanced and Quality, each with its effort and a backup from another maker, so
a usage pool that turns `tight` or `exhausted` moves a step to another column
instead of the roadmap being refreshed. On 2026-10-23 they asked for each
column ranked three deep (pick, runner-up, backup), each option with its AA
Index. On 2026-10-24 they found the table of one field a row unreadable in a
Markdown preview 400–520px wide, so each column is a list, one option a line.
scoring.settings_ladder reads the ladder with every pool at headroom and
prints the lists and their **Runs:** line; `roadmodel ladder` and the MCP tool
`roadmap_settings` serve it, and `roadmodel relayout` converts the tables
older releases wrote.

The fixture: Lite, Luna and Astra are one maker's (Codex), Sonnet and Opus
another's (Claude Code), as in tests/test_ladder_frontier.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from roadmodel import ladder_layout, recommend, scoring
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


_TIER_HEAD = re.compile(r"^\*\*(Cost|Balanced|Quality)\*\*( — runs by default)?$")
_ITEM = re.compile(r"^- (Pick|Runner-up|Backup): (.*)$")
RANKS = ("Pick", "Runner-up", "Backup")


def _listed(markdown: str) -> dict[str, dict[str, dict[str, str] | None]]:
    """The ladder's options by tier and rank, each option's fields (model,
    platform, and the dial, Thinking and AA fields it carries), its wrapped
    lines joined; None for a rank that reads ``none``."""
    out: dict[str, dict[str, dict[str, str] | None]] = {}
    tier = ""
    for line in markdown.replace("\n  · ", " · ").splitlines():
        if head := _TIER_HEAD.match(line):
            tier = head.group(1).lower()
            out[tier] = {}
        elif (item := _ITEM.match(line)) and tier:
            rank, rest = item.groups()
            if rest == "none":
                out[tier][rank] = None
                continue
            model, platform, *more = rest.split(" · ")
            fields = {"model": model.strip("*"), "platform": platform}
            for f in more:
                if f.startswith("Thinking "):
                    fields["thinking"] = f.removeprefix("Thinking ")
                elif f.startswith("AA "):
                    fields["aa"] = f.removeprefix("AA ")
                else:
                    fields["effort"] = f
            out[tier][rank] = fields
    return out


def _option_fields(option: dict[str, Any] | None) -> dict[str, str] | None:
    """A column's option as its list line should carry it: no field for a
    dial or toggle the surface lacks."""
    if option is None:
        return None
    fields = {"model": option["model"], "platform": option["platform"]}
    if option["effort_cell"] != "—":
        fields["effort"] = option["effort_cell"]
    if option["thinking_cell"] != "—":
        fields["thinking"] = option["thinking_cell"]
    fields["aa"] = scoring._aa_cell(option["aa_index"])
    return fields


def _options(col: dict[str, Any]) -> tuple[Any, Any, Any]:
    return col, col["runner_up"], col["backup"]


def test_each_column_ranks_its_pick_runner_up_and_backup() -> None:
    lad = scoring.ladder(PLANNING_MEDIUM, _context(), catalog=CATALOG, benchmarks=BENCH)
    assert lad is not None
    got = _settings()
    for tier, rung in lad.rungs.items():
        col = got["columns"][tier]
        assert (col["model"], col["platform"]) == (
            rung.candidate.model_name,
            rung.candidate.platform_name,
        )
        # The runner-up is the column's pick with the pick's model off the table.
        rest = scoring.ladder(
            PLANNING_MEDIUM,
            _context(),
            unavailable_models=[rung.candidate.model_id],
            catalog=CATALOG,
            benchmarks=BENCH,
            neutral_pools=True,
        )
        assert rest is not None
        assert col["runner_up"]["model_id"] == rest.rungs[tier].candidate.model_id
        # The backup is another maker's than the pick's, and never the runner-up.
        backup = col["backup"]
        if backup is not None:
            assert backup["model_id"] not in {col["model_id"], col["runner_up"]["model_id"]}
            makers = {m["id"]: m["provider"] for m in CATALOG["models"]}
            assert makers[backup["model_id"]] != makers[col["model_id"]]
    paragraphs = got["markdown"].split("\n\n")
    heads = [p for p in paragraphs if _TIER_HEAD.match(p)]
    assert heads == ["**Cost**", "**Balanced** — runs by default", "**Quality**"]
    assert paragraphs[-2] == "**Conversation:** New"
    listed = _listed(got["markdown"])
    assert list(listed) == list(scoring.LADDER_TIERS)
    for tier in scoring.LADDER_TIERS:
        col = got["columns"][tier]
        assert list(listed[tier]) == list(RANKS)
        for rank, option in zip(RANKS, _options(col), strict=True):
            assert listed[tier][rank] == _option_fields(option), (tier, rank)


def test_each_option_takes_one_line_and_the_source_fits_80_columns() -> None:
    """One option a line, model first, so it reads in a narrow preview, and
    no table or `<br>` cell; every line, the wrapped Runs paragraph included,
    fits the 80 columns a roadmap's prose wraps at."""
    got = _settings()
    md = got["markdown"]
    assert "<br>" not in md and "&emsp;" not in md
    assert not any(ln.startswith("|") for ln in md.splitlines())
    assert all(len(ln) <= 80 for ln in md.splitlines())


def test_a_long_option_wraps_between_fields() -> None:
    """A line past 80 columns breaks before a field, never inside one, and
    its continuation stays in the list item."""
    option = ladder_layout.Option(
        model="Gemini 3.8 Flash",
        platform="Antigravity",
        effort="Effort Medium",
        thinking="On",
        aa="39.8",
    )
    line = ladder_layout.option_line("Runner-up", option)
    first, rest = line.split("\n")
    assert first == "- Runner-up: **Gemini 3.8 Flash** · Antigravity · Effort Medium · Thinking On"
    assert rest == "  · AA 39.8"
    assert ladder_layout.option_line("Backup", None) == "- Backup: none"
    # A surface without a dial or toggle gets no field for it.
    bare = ladder_layout.Option(model="Composer 2", platform="Cursor", aa="not measured")
    assert ladder_layout.option_line("Pick", bare) == (
        "- Pick: **Composer 2** · Cursor · AA not measured"
    )


def test_the_runner_up_is_never_an_older_version_of_the_pick() -> None:
    """Off the table, GPT-6.1 Sol would hand its place to GPT-6 Sol, which the
    operator's rule never recommends where GPT-6.1 Sol runs: the runner-up
    leaves out the pick's whole series."""
    catalog = {
        **CATALOG,
        "models": [
            *(
                {**m, "id": "gpt-6.1-luna", "name": "GPT-6.1 Luna"} if m["id"] == "luna" else m
                for m in CATALOG["models"]
            ),
            _model("gpt-6-luna", "GPT-6 Luna", 0.25, 1.25, "A", "openai"),
        ],
        "access_methods": [
            {**a, "supports_models": ["lite", "gpt-6.1-luna", "gpt-6-luna", "astra"]}
            if a["id"] == "codex-cli"
            else a
            for a in CATALOG["access_methods"]
        ],
    }
    bench = {
        **{k: v for k, v in BENCH.items() if k != "luna"},
        "gpt-6.1-luna": BENCH["luna"],
        "gpt-6-luna": _aa(39),
    }
    got = scoring.settings_ladder(PLANNING_MEDIUM, _context(), catalog=catalog, benchmarks=bench)
    assert got is not None
    cols = got["columns"].values()
    assert any(c["model_id"] == "gpt-6.1-luna" for c in cols), "the fixture picks GPT-6.1 Luna"
    for col in cols:
        others = [col["runner_up"], col["backup"]]
        assert all(o is None or o["model_id"] != "gpt-6-luna" for o in others)


GOOGLE: dict[str, Any] = {
    **CATALOG,
    # Dearer than Opus: without the third-maker rule, Cost's backup would be
    # Opus, the runner-up Sonnet's maker.
    "models": [*CATALOG["models"], _model("argon", "Argon", 5.0, 25.0, "S", "google")],
    "access_methods": [
        *CATALOG["access_methods"],
        {
            "id": "antigravity",
            "name": "Antigravity",
            "provider": "google",
            "provider_jurisdiction": "us",
            "billing": "subscription-or-key",
            "supports_models": ["argon"],
            "effort_levels": ["low", "medium", "high"],
        },
    ],
    "subscription_tiers": [
        *CATALOG["subscription_tiers"],
        {
            "provider": "Google",
            "tier": "Google AI Pro ($20)",
            "monthly_usd": 20.0,
            "surface_funded": ["antigravity"],
        },
    ],
}


def test_the_backup_comes_from_a_maker_neither_row_above_uses() -> None:
    """With three makers funded, a column whose runner-up is another maker's
    takes its backup from the third, so the three rows span three pools."""
    text = _context().replace(
        "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
        "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |\n"
        "| Google AI Pro ($20) | $20 | Google | Antigravity |",
    )
    bench = {**BENCH, "argon": _aa(54)}
    got = scoring.settings_ladder(PLANNING_MEDIUM, text, catalog=GOOGLE, benchmarks=bench)
    assert got is not None
    makers = {m["id"]: m["provider"] for m in GOOGLE["models"]}
    spread = [
        col
        for col in got["columns"].values()
        if makers[col["runner_up"]["model_id"]] != makers[col["model_id"]]
    ]
    assert spread, "the fixture puts another maker's runner-up in some column"
    for col in spread:
        assert col["backup"] is not None
        ranked = [col["model_id"], col["runner_up"]["model_id"], col["backup"]["model_id"]]
        assert len({makers[m] for m in ranked}) == 3, ranked


def test_a_runner_up_holding_the_only_other_maker_leaves_no_backup() -> None:
    """Two makers, one series each: the runner-up already is the other maker,
    so no backup can be both another maker's and distinct from it."""
    catalog = {
        **CATALOG,
        "models": [m for m in CATALOG["models"] if m["id"] in {"opus", "astra"}],
        "access_methods": [
            {**a, "supports_models": [m for m in a["supports_models"] if m in {"opus", "astra"}]}
            for a in CATALOG["access_methods"]
        ],
    }
    got = scoring.settings_ladder(PLANNING_MEDIUM, _context(), catalog=catalog, benchmarks=BENCH)
    assert got is not None
    for col in got["columns"].values():
        assert col["runner_up"]["model_id"] != col["model_id"]
        assert col["backup"] is None
    listed = _listed(got["markdown"])
    assert all(listed[t]["Backup"] is None for t in scoring.LADDER_TIERS)
    assert got["markdown"].count("- Backup: none") == 3


def _aa(value: float) -> dict[str, Any]:
    return {"evaluations": {"artificial_analysis_intelligence_index": value}}


def test_every_option_reads_its_models_index_at_its_own_effort() -> None:
    """Each ranked option's AA Index is its model at its own effort, not the
    model's headline: GPT-6 Luna reads 21.5 at low and 38.1 at max."""
    levels = ("low", "medium", "high", "xhigh")
    bench = {
        mid: {
            **_aa(aa),
            "aa_effort": "max",
            "effort_variants": {lv: _aa(aa - 4 * (len(levels) - i)) for i, lv in enumerate(levels)},
        }
        for mid, aa in {"lite": 20, "luna": 40, "sonnet": 55, "opus": 58, "astra": 52}.items()
    }
    got = scoring.settings_ladder(PLANNING_MEDIUM, _context(), catalog=CATALOG, benchmarks=bench)
    assert got is not None
    for col in got["columns"].values():
        for option in (col, col["runner_up"], col["backup"]):
            assert option is not None
            measured = scoring.measured_levels(bench, option["model_id"])[option["effort"]]
            want = measured["evaluations"]["artificial_analysis_intelligence_index"]
            assert option["aa_index"] == want
    listed = _listed(got["markdown"])
    for tier in scoring.LADDER_TIERS:
        for rank, option in zip(RANKS, _options(got["columns"][tier]), strict=True):
            fields = listed[tier][rank]
            assert fields is not None
            assert fields["aa"] == f"{option['aa_index']:g}"


def test_ladder_aa_index_reads_the_effort_or_says_not_measured() -> None:
    per_level = {"m": {**_aa(50), "aa_effort": "max", "effort_variants": {"low": _aa(30)}}}
    assert scoring.ladder_aa_index(per_level, "m", "max") == 50
    assert scoring.ladder_aa_index(per_level, "m", "low") == 30
    # Measured at other efforts only: no figure stands for this one.
    assert scoring.ladder_aa_index(per_level, "m", "high") is None
    assert scoring.ladder_aa_index(per_level, "m", "high", dial=True) is None
    # AA names no level: on a surface with no dial the row stands for the
    # model as it runs there …
    assert scoring.ladder_aa_index({"m": _aa(44)}, "m", "high") == 44
    # … but where the operator sets a level, the row's effort is unknown, so
    # it is no figure for the level set (Gemini 3 Flash on the Google API).
    assert scoring.ladder_aa_index({"m": _aa(44)}, "m", "low", dial=True) is None
    assert scoring.ladder_aa_index({}, "m", "high") is None
    assert scoring._aa_cell(None) == "not measured"


def test_an_unlabeled_aa_row_is_not_shown_at_a_level_the_operator_sets() -> None:
    """The fixture's AA rows name no effort and both surfaces have a dial, so
    no option claims a figure for the level it runs at."""
    got = _settings()
    for col in got["columns"].values():
        for option in _options(col):
            if option is not None:
                assert option["aa_index"] is None
    assert "AA not measured" in got["markdown"]


def test_each_column_names_its_own_surfaces_dial() -> None:
    cols = _settings()["columns"]
    for col in cols.values():
        if col["platform_id"] == "codex-cli":
            assert col["effort_cell"].startswith("Intelligence ")
            assert col["thinking_cell"] == "—"
        else:
            assert col["effort_cell"].startswith("Effort ")
            assert col["thinking_cell"] == "On"


def test_a_model_that_always_thinks_has_no_thinking_toggle() -> None:
    """Claude Code shows no Thinking switch on a model that always thinks
    (2.1.281 / 2.1.300), so its cell carries no Thinking line, like a surface
    without the toggle."""
    always = {
        **CATALOG,
        "models": [
            {**m, "always_thinks": True} if m["id"] in {"sonnet", "opus"} else m
            for m in CATALOG["models"]
        ],
    }
    got = scoring.settings_ladder(PLANNING_MEDIUM, _context(), catalog=always, benchmarks=BENCH)
    assert got is not None
    claude = [c for c in got["columns"].values() if c["platform_id"] == "claude-code"]
    assert claude, "the fixture ladder puts a Claude Code model in some column"
    assert all(c["thinking_cell"] == "—" for c in claude)
    assert all(c["effort_cell"].startswith("Effort ") for c in claude)
    listed = _listed(got["markdown"])
    for tier in scoring.LADDER_TIERS:
        if got["columns"][tier]["platform_id"] == "claude-code":
            pick = listed[tier]["Pick"]
            assert pick is not None and "thinking" not in pick


@pytest.mark.parametrize(
    ("budget", "runs"), [("cheap", "cost"), ("balanced", "balanced"), ("best", "quality")]
)
def test_the_step_runs_the_column_its_budget_priority_names(budget: str, runs: str) -> None:
    got = _settings(scoring.Task("planning", "medium", budget=budget))
    assert got["runs"] == runs
    paragraphs = got["markdown"].split("\n\n")
    assert f"**{runs.capitalize()}** — runs by default" in paragraphs
    assert sum("runs by default" in p for p in paragraphs) == 1
    runs_line = paragraphs[-1]
    assert runs_line.startswith(f"**Runs:** {runs.capitalize()} — ")
    assert scoring.RUN_RULE in " ".join(runs_line.split())


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
    assert out.startswith("**Cost**\n\n- Pick: **")
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


# reversi's Phase 31.6 Step 3 as roadmodel 0.2.93 wrote it.
RANKED_TABLE = """\
**Deploys:** CI → live on merge.

| Rank          | Cost              | Balanced           | Quality        |
| ------------- | ----------------- | ------------------ | -------------- |
| 1 · Pick      | GPT-6.1 Sol       | Gemini 4 Argon     | Opus 5.5       |
| Platform      | Codex             | Antigravity        | Claude Code    |
| Effort        | Intelligence High | Effort High        | Effort XHigh   |
| Thinking      | —                 | On                 | —              |
| AA Index      | 50.2              | 52.6               | 56             |
| 2 · Runner-up | Sonnet 5.5        | Opus 5.5           | Fable 5.1      |
| Platform      | Claude Code       | Claude Code        | Claude Code    |
| Effort        | Effort XHigh      | Effort High        | Effort XHigh   |
| Thinking      | —                 | —                  | —              |
| AA Index      | 51.9              | 53.6               | 53.2           |
| 3 · Backup    | Gemini 4 Argon    | GPT-6.1 Sol        | None           |
| Platform      | Antigravity       | Codex              | —              |
| Effort        | Effort High       | Intelligence XHigh | —              |
| Thinking      | On                | —                  | —              |
| AA Index      | 52.6              | 51                 | —              |
| Conversation  | **New**           | **New**            | **New**        |

**Runs:** Balanced — the user-context's Budget priority is `balanced`. If that
column's usage pool reads `tight` or `exhausted`, run the first of its Runner-up
and Backup whose pool has headroom; with neither, a `tight` column runs the Cost
column and an `exhausted` one its Backup.

**Model rationale:** unchanged.
"""

RANKED_LISTS = """\
**Deploys:** CI → live on merge.

**Cost**

- Pick: **GPT-6.1 Sol** · Codex · Intelligence High · AA 50.2
- Runner-up: **Sonnet 5.5** · Claude Code · Effort XHigh · AA 51.9
- Backup: **Gemini 4 Argon** · Antigravity · Effort High · Thinking On · AA 52.6

**Balanced** — runs by default

- Pick: **Gemini 4 Argon** · Antigravity · Effort High · Thinking On · AA 52.6
- Runner-up: **Opus 5.5** · Claude Code · Effort High · AA 53.6
- Backup: **GPT-6.1 Sol** · Codex · Intelligence XHigh · AA 51

**Quality**

- Pick: **Opus 5.5** · Claude Code · Effort XHigh · AA 56
- Runner-up: **Fable 5.1** · Claude Code · Effort XHigh · AA 53.2
- Backup: none

**Conversation:** New

**Runs:** Balanced — the user-context's Budget priority is `balanced`. If that
column's usage pool reads `tight` or `exhausted`, run the first of its Runner-up
and Backup whose pool has headroom; with neither, a `tight` column runs the Cost
column and an `exhausted` one its Backup.

**Model rationale:** unchanged.
"""


def test_relayout_turns_a_ranked_table_into_the_lists_keeping_every_value() -> None:
    new, count = ladder_layout.relayout(RANKED_TABLE)
    assert count == 1
    assert new == RANKED_LISTS
    # A second pass finds nothing left to convert.
    assert ladder_layout.relayout(new) == (new, 0)


def test_relayout_reads_the_single_pick_ladders_older_releases_wrote() -> None:
    """0.2.86–0.2.92 ladders: a pick, and a backup in one cell or split into
    rows on a Complete step (0.2.93). The backup never carried an AA Index,
    so its line has none; a surface with no dial gets no dial field."""
    split = """\
| Setting       | Cost             | Balanced       | Quality        |
| ------------- | ---------------- | -------------- | -------------- |
| Model         | GPT-6.1 Sol      | Gemini 4 Argon | Opus 5.5       |
| Backup        | Sonnet 5.5       | Opus 5.5       | Gemini 4 Argon |
| Backup on     | Claude Code      | Claude Code    | Antigravity    |
| Backup effort | Effort Medium    | Effort High    | Effort High    |
| Platform      | Codex            | Antigravity    | Claude Code    |
| Effort        | Intelligence Low | Effort High    | Effort High    |
| AA Index      | 42.1             | 52.6           | 53.6           |
| Thinking      | —                | On             | —              |
| Conversation  | **New**          | **New**        | **New**        |

**Runs:** Quality — a phase-roadmap session runs Quality (quality first)."""
    new, count = ladder_layout.relayout(split)
    assert count == 1
    assert new.startswith(
        "**Cost**\n\n"
        "- Pick: **GPT-6.1 Sol** · Codex · Intelligence Low · AA 42.1\n"
        "- Backup: **Sonnet 5.5** · Claude Code · Effort Medium\n\n"
        "**Balanced**\n\n"
        "- Pick: **Gemini 4 Argon** · Antigravity · Effort High · Thinking On · AA 52.6\n"
        "- Backup: **Opus 5.5** · Claude Code · Effort High\n\n"
        "**Quality** — runs by default\n\n"
        "- Pick: **Opus 5.5** · Claude Code · Effort High · AA 53.6\n"
        "- Backup: **Gemini 4 Argon** · Antigravity · Effort High\n\n"
        "**Conversation:** New\n\n**Runs:** Quality"
    )
    one_cell = """\
| Setting      | Cost                                   | Balanced              | Quality  |
| ------------ | -------------------------------------- | --------------------- | -------- |
| Model        | GPT-6.1 Sol                            | Composer 2            | Opus 5.5 |
| Backup       | Sonnet 5.5 — Claude Code · Effort High | GPT-6.1 Sol — Cursor  | None     |
| Platform     | Codex                                  | Cursor                | Claude Code |
| Effort       | Intelligence Medium                    | —                     | Effort Max |
| Thinking     | —                                      | —                     | —        |
| Conversation | **New**                                | **New**               | **New**  |
"""
    listed = _listed(ladder_layout.relayout(one_cell)[0])
    assert listed["cost"]["Backup"] == {
        "model": "Sonnet 5.5",
        "platform": "Claude Code",
        "effort": "Effort High",
    }
    assert listed["balanced"]["Pick"] == {"model": "Composer 2", "platform": "Cursor"}
    assert listed["balanced"]["Backup"] == {"model": "GPT-6.1 Sol", "platform": "Cursor"}
    assert listed["quality"]["Backup"] is None
    assert "Runner-up" not in ladder_layout.relayout(one_cell)[0]


def test_relayout_leaves_a_table_it_does_not_know() -> None:
    odd = RANKED_TABLE.replace(
        "| Thinking      | —                 | On ", "| Speed         | —                 | On ", 1
    )
    assert ladder_layout.relayout(odd) == (odd, 0)
    other = "| Item | Cost |\n| --- | --- |\n| EIN | $0 |\n"
    assert ladder_layout.relayout(other) == (other, 0)


def test_relayout_command_rewrites_the_files_and_check_reports_them(tmp_path: Path) -> None:
    roadmap = tmp_path / "phase31.6-roadmap.md"
    roadmap.write_text(RANKED_TABLE, encoding="utf-8")
    check = CliRunner().invoke(cli, ["relayout", "--check", str(roadmap)])
    assert check.exit_code == 1 and "1 ladder table" in check.output
    assert roadmap.read_text(encoding="utf-8") == RANKED_TABLE
    done = CliRunner().invoke(cli, ["relayout", str(roadmap)])
    assert done.exit_code == 0, done.output
    assert roadmap.read_text(encoding="utf-8") == RANKED_LISTS
    again = CliRunner().invoke(cli, ["relayout", "--check", str(roadmap)])
    assert again.exit_code == 0 and again.output == ""


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
