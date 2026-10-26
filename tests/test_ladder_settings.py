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


RANKS = ("Pick", "Runner‑up", "Backup")
FIELDS = ("Model", "Platform", "Level", "AA", "Price")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tabled(markdown: str) -> tuple[list[str], dict[str, dict[str, dict[str, str]]]]:
    """The ladder table's header and its cells by tier, rank and field (the
    field label with its `&nbsp;` indent removed)."""
    lines = [ln for ln in markdown.splitlines() if ln.startswith("|")]
    head = _cells(lines[0])
    out: dict[str, dict[str, dict[str, str]]] = {t: {} for t in scoring.LADDER_TIERS}
    rank = ""
    for line in lines[2:]:
        label, *cells = _cells(line)
        if label.startswith("**"):
            rank = label.strip("*")
            assert cells == ["", "", ""], line
            for t in scoring.LADDER_TIERS:
                out[t][rank] = {}
            continue
        assert label.startswith(ladder_layout.INDENT), line
        for t, cell in zip(scoring.LADDER_TIERS, cells, strict=True):
            out[t][rank][label.removeprefix(ladder_layout.INDENT)] = cell
    return head, out


def _option_cells(option: dict[str, Any] | None) -> dict[str, str]:
    """A column's option as its table cells should read it."""
    if option is None:
        return dict(zip(FIELDS, ["none", "—", "—", "—", "—"], strict=True))
    price = option["price_usd_per_1m"]
    return {
        "Model": f"**{option['model']}**",
        "Platform": option["platform"],
        "Level": option["level_cell"] + (" ↓" if option["stepped_down"] else ""),
        "AA": scoring._aa_cell(option["aa_index"]),
        "Price": "—"
        if price is None
        else f"${price:.2f}/1M" + ("" if option["price_measured"] else "*"),
    }


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
        # The runner-up is the column's pick with the pick's whole maker off
        # the table: a tight pool is a maker's.
        makers = {m["id"]: m["provider"] for m in CATALOG["models"]}
        own = [m for m, p in makers.items() if p == makers[col["model_id"]]]
        rest = scoring.ladder(
            PLANNING_MEDIUM,
            _context(),
            unavailable_models=own,
            catalog=CATALOG,
            benchmarks=BENCH,
            neutral_pools=True,
        )
        assert rest is not None
        assert col["runner_up"]["model_id"] == rest.rungs[tier].candidate.model_id
        assert makers[col["runner_up"]["model_id"]] != makers[col["model_id"]]
        # Two makers funded: the backup is the pick one level lower (↓).
        backup = col["backup"]
        if backup is not None:
            assert backup["stepped_down"] and backup["model_id"] == col["model_id"]
    head, cells = _tabled(got["markdown"])
    assert head == ["", "Cost", "Balanced ✓", "Quality"]
    paragraphs = got["markdown"].split("\n\n")
    assert paragraphs[-2] == "**Conversation:** New"
    for tier in scoring.LADDER_TIERS:
        col = got["columns"][tier]
        assert list(cells[tier]) == list(RANKS)
        for rank, option in zip(RANKS, _options(col), strict=True):
            assert cells[tier][rank] == _option_cells(option), (tier, rank)


def test_the_table_groups_each_rank_over_indented_field_rows() -> None:
    """2026-10-24: the operator chose this table after reading candidates in
    a Markdown preview 400–520px wide. Cost / Balanced / Quality are the
    columns; each rank is a bold group row over indented Model / Platform /
    Level / AA / Price rows. Level is the bare level and no row carries
    Thinking (a ladder only recommends it On); no `<br>` cell; the prose
    under the table wraps at 80."""
    md = _settings()["markdown"]
    rows = [_cells(ln) for ln in md.splitlines() if ln.startswith("|")][2:]
    labels = [r[0] for r in rows]
    assert labels == [
        label
        for rank in RANKS
        for label in (f"**{rank}**", *(ladder_layout.INDENT + f for f in FIELDS))
    ]
    assert "Thinking" not in md and "<br>" not in md
    assert not any(c.startswith(("Effort ", "Intelligence ")) for r in rows for c in r[1:])
    prose = [ln for ln in md.splitlines() if not ln.startswith("|")]
    assert all(len(ln) <= 80 for ln in prose)
    flat = " ".join(" ".join(prose).split())
    assert "✓ runs by default." in flat
    assert "Price: list $ per 1M tokens (3 in : 1 out)" in flat


def test_price_is_the_list_price_at_the_levels_token_use() -> None:
    """Price is the frontier's price axis: the blended list price (3 in : 1
    out) times the output tokens the model draws at the level, measured where
    docs/effort-tokens.json has it; an unmeasured level is marked."""
    sol = {"models": [{"id": "s", "input_price_per_1m": 2.0, "output_price_per_1m": 10.0}]}
    price, measured = scoring.ladder_price("s", "xhigh", sol)  # type: ignore[misc]
    assert price == round(4.0 * scoring.EFFORT_TOKEN_MULTIPLIER["xhigh"], 4)
    assert measured is False
    assert scoring.ladder_price("missing", "high", sol) is None
    # Codex's `ultra` and Gemini's `minimal` price at the scorer level they stand for.
    assert scoring.ladder_price("s", "ultra", sol) == scoring.ladder_price("s", "max", sol)
    assert scoring.ladder_price("s", "minimal", sol) == scoring.ladder_price("s", "low", sol)
    cell = ladder_layout.price_cell
    assert cell(ladder_layout.Option("m", "p", price=2.1834)) == "$2.18/1M"
    assert cell(ladder_layout.Option("m", "p", price=4.0, price_measured=False)) == "$4.00/1M*"
    assert cell(ladder_layout.Option("m", "p")) == "—"
    by_name = scoring.ladder_price_by_name({"models": [{"name": "Sol", **sol["models"][0]}]})
    assert by_name("Sol", "XHigh") == scoring.ladder_price("s", "xhigh", sol)
    assert by_name("Sol", "—") == scoring.ladder_price("s", "high", sol)
    assert by_name("Gone 1", "High") is None and by_name("Sol", "Turbo") is None


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


def test_three_funded_makers_give_each_rank_its_own_maker() -> None:
    """2026-10-25: Quality ranked Opus 5.5 then Fable 5.1, two Anthropic
    models drawing one Claude Max pool, so the runner-up was no fallback for
    a tight pool. With three makers funded, every column's Pick, Runner-up and
    Backup come from three makers, none stepped down."""
    text = _context().replace(
        "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |",
        "| ChatGPT Pro ($100) | $100 | OpenAI | Codex |\n"
        "| Google AI Pro ($20) | $20 | Google | Antigravity |",
    )
    bench = {**BENCH, "argon": _aa(54)}
    got = scoring.settings_ladder(PLANNING_MEDIUM, text, catalog=GOOGLE, benchmarks=bench)
    assert got is not None
    makers = {m["id"]: m["provider"] for m in GOOGLE["models"]}
    for col in got["columns"].values():
        options = _options(col)
        assert all(o is not None and not o["stepped_down"] for o in options)
        assert len({makers[o["model_id"]] for o in options}) == 3, col
    _, cells = _tabled(got["markdown"])
    assert not any(
        cells[t][rank]["Level"].endswith("↓") for t in scoring.LADDER_TIERS for rank in RANKS
    )


def test_too_few_makers_step_the_pick_down_a_level() -> None:
    """With two makers the backup, and with one the runner-up and backup, are
    the Pick's own model one and two levels lower (↓): on a tight pool a
    lower level uses less of it. Below the dial's lowest level a rank reads
    none."""
    got = _settings()
    for col in got["columns"].values():
        backup = col["backup"]
        assert backup is not None and backup["stepped_down"]
        assert backup["model_id"] == col["model_id"]
        assert scoring.EFFORT_LADDER.index(backup["effort"]) == (
            scoring.EFFORT_LADDER.index(col["effort"]) - 1
        )
    _, cells = _tabled(got["markdown"])
    assert all(cells[t]["Backup"]["Level"].endswith(" ↓") for t in scoring.LADDER_TIERS)
    assert "↓ the Pick one level lower: no other maker is funded" in " ".join(
        got["markdown"].split()
    )
    one = {
        **CATALOG,
        "models": [m for m in CATALOG["models"] if m["provider"] == "anthropic"],
        "access_methods": [a for a in CATALOG["access_methods"] if a["id"] == "claude-code"],
        "subscription_tiers": CATALOG["subscription_tiers"][:1],
    }
    alone = scoring.settings_ladder(PLANNING_MEDIUM, _context(), catalog=one, benchmarks=BENCH)
    assert alone is not None
    for col in alone["columns"].values():
        steps = scoring.EFFORT_LADDER.index(col["effort"])
        for rank, option in ((1, col["runner_up"]), (2, col["backup"])):
            if steps < rank:
                assert option is None
                continue
            assert option is not None and option["stepped_down"]
            assert option["model_id"] == col["model_id"]
            assert scoring.EFFORT_LADDER.index(option["effort"]) == steps - rank


def test_the_note_names_the_classification_the_ladder_was_ranked_for() -> None:
    """A ladder carries its classification, so a later re-ranking needs no
    one to re-read the step's prose."""
    md = _settings(scoring.Task("coding", "high", True))["markdown"]
    assert "Ranked for coding, high complexity, novel." in " ".join(md.split())
    assert "Ranked for planning, medium complexity." in " ".join(_settings()["markdown"].split())


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
    checked = 0
    for col in got["columns"].values():
        # A pick at its dial's lowest level has no level below it to step to.
        for option in (o for o in _options(col) if o is not None):
            measured = scoring.measured_levels(bench, option["model_id"])[option["effort"]]
            want = measured["evaluations"]["artificial_analysis_intelligence_index"]
            assert option["aa_index"] == want
            checked += 1
    assert checked >= 7
    _, cells = _tabled(got["markdown"])
    for tier in scoring.LADDER_TIERS:
        for rank, option in zip(RANKS, _options(got["columns"][tier]), strict=True):
            if option is not None:
                assert cells[tier][rank]["AA"] == f"{option['aa_index']:g}"


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
    _, cells = _tabled(got["markdown"])
    assert {cells[t]["Pick"]["AA"] for t in scoring.LADDER_TIERS} == {"not measured"}


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
    assert "Thinking" not in got["markdown"]


@pytest.mark.parametrize(
    ("budget", "runs"), [("cheap", "cost"), ("balanced", "balanced"), ("best", "quality")]
)
def test_the_step_runs_the_column_its_budget_priority_names(budget: str, runs: str) -> None:
    got = _settings(scoring.Task("planning", "medium", budget=budget))
    assert got["runs"] == runs
    head, _ = _tabled(got["markdown"])
    assert head[1:] == [t.capitalize() + (" ✓" if t == runs else "") for t in scoring.LADDER_TIERS]
    runs_line = got["markdown"].split("\n\n")[-1]
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
    assert _cells(out.splitlines()[0]) == ["", "Cost", "Balanced ✓", "Quality"]
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


# reversi's Phase 31.6 Step 3 as roadmodel 0.2.93 wrote it (its Quality
# backup made None here).
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

# The same ladder as 0.2.94 printed it.
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
- Runner-up: **Fable 5.1** · Claude Code
  · Effort XHigh · AA 53.2
- Backup: none

**Conversation:** New

**Runs:** Balanced — the user-context's Budget priority is `balanced`. If that
column's usage pool reads `tight` or `exhausted`, run the first of its Runner-up
and Backup whose pool has headroom; with neither, a `tight` column runs the Cost
column and an `exhausted` one its Backup.

**Model rationale:** unchanged.
"""


def _fake_price(name: str, word: str) -> tuple[float, bool] | None:
    """A price per name and level that tests can predict: unknown for a
    model named `Gone`, unmeasured at any level but High."""
    return None if name.startswith("Gone") else (len(name) + 0.5, word == "High")


def _priced(name: str, word: str) -> str:
    found = _fake_price(name, word)
    assert found is not None
    return f"${found[0]:.2f}/1M" + ("" if found[1] else "*")


def test_relayout_turns_a_ranked_table_into_the_ladder_table() -> None:
    new, count, kept = ladder_layout.relayout(RANKED_TABLE, price=_fake_price)
    assert (count, kept) == (1, 0)
    head, cells = _tabled(new)
    assert head == ["", "Cost", "Balanced ✓", "Quality"]
    assert cells["cost"]["Pick"] == {
        "Model": "**GPT-6.1 Sol**",
        "Platform": "Codex",
        "Level": "High",
        "AA": "50.2",
        "Price": _priced("GPT-6.1 Sol", "High"),
    }
    assert cells["balanced"]["Backup"]["Level"] == "XHigh"
    assert cells["quality"]["Runner‑up"]["Price"] == _priced("Fable 5.1", "XHigh")
    assert cells["quality"]["Backup"]["Model"] == "none"
    # Everything around the ladder is kept, and Thinking has no row.
    assert new.startswith("**Deploys:** CI → live on merge.\n\n|")
    assert new.endswith(RANKED_TABLE[RANKED_TABLE.index("**Runs:**") :])
    assert "\n\n**Conversation:** New\n\n**Runs:**" in new
    assert "Thinking" not in new.split("**Runs:**")[0]
    assert "* token use not yet measured" in new
    # A second pass finds nothing left to convert.
    assert ladder_layout.relayout(new, price=_fake_price) == (new, 0, 0)


def test_relayout_reads_the_lists_0_2_94_printed() -> None:
    """The lists carry the same values, wrapped lines included, and mark the
    column that runs on its heading."""
    from_lists = ladder_layout.relayout(RANKED_LISTS, price=_fake_price)
    assert from_lists == ladder_layout.relayout(RANKED_TABLE, price=_fake_price)


def test_relayout_reads_the_single_pick_ladders_older_releases_wrote() -> None:
    """0.2.86–0.2.92 ladders: a pick, and a backup in one cell or split into
    rows (0.2.93). The backup never carried an AA Index, so that group has no
    AA row; a model the catalog no longer carries has no price."""
    split = """\
| Setting       | Cost             | Balanced       | Quality        |
| ------------- | ---------------- | -------------- | -------------- |
| Model         | GPT-6.1 Sol      | Gemini 4 Argon | Gone 1         |
| Backup        | Sonnet 5.5       | Opus 5.5       | Gemini 4 Argon |
| Backup on     | Claude Code      | Claude Code    | Antigravity    |
| Backup effort | Effort Medium    | Effort High    | Effort High    |
| Platform      | Codex            | Antigravity    | Claude Code    |
| Effort        | Intelligence Low | Effort High    | Effort High    |
| AA Index      | 42.1             | 52.6           | 53.6           |
| Thinking      | —                | On             | —              |
| Conversation  | **New**          | **New**        | **New**        |

**Runs:** Quality — a phase-roadmap session runs Quality (quality first)."""
    new, count, _ = ladder_layout.relayout(split, price=_fake_price)
    assert count == 1
    head, cells = _tabled(new)
    assert head == ["", "Cost", "Balanced", "Quality ✓"]
    assert list(cells["cost"]) == ["Pick", "Backup"]
    assert cells["cost"]["Backup"] == {
        "Model": "**Sonnet 5.5**",
        "Platform": "Claude Code",
        "Level": "Medium",
        "Price": _priced("Sonnet 5.5", "Medium"),
    }
    assert cells["quality"]["Pick"]["Price"] == "—"
    one_cell = """\
| Setting      | Cost                                   | Balanced             | Quality     |
| ------------ | -------------------------------------- | -------------------- | ----------- |
| Model        | GPT-6.1 Sol                            | Composer 2           | Opus 5.5    |
| Backup       | Sonnet 5.5 — Claude Code · Effort High | GPT-6.1 Sol — Cursor | None        |
| Platform     | Codex                                  | Cursor               | Claude Code |
| Effort       | Intelligence Medium                    | —                    | Effort Max  |
| Thinking     | —                                      | —                    | —           |
| Conversation | **New**                                | **New**              | **New**     |
"""
    _, cells = _tabled(ladder_layout.relayout(one_cell, price=_fake_price)[0])
    assert cells["cost"]["Backup"]["Level"] == "High"
    assert cells["balanced"]["Pick"]["Level"] == "—"
    assert cells["balanced"]["Backup"]["Platform"] == "Cursor"
    assert cells["quality"]["Backup"]["Model"] == "none"
    assert cells["quality"]["Pick"]["Level"] == "Max"


def test_relayout_keeps_the_ladder_of_a_step_that_ran_or_runs() -> None:
    """A Complete step's ladder is the record of what ran, an In progress
    one's is what an agent is running, and a written phase's records what
    wrote its roadmap: all stay as written."""
    table = RANKED_TABLE[RANKED_TABLE.index("| Rank") : RANKED_TABLE.index("**Runs:**")]
    doc = "\n\n".join(
        [
            "## Step 1 — Done ✅",
            "**Status:** Complete — PR #1",
            table,
            "## Step 2 — Running",
            "**Status:** In progress — PR #2",
            table,
            "## Step 3 — Next",
            "**Status:** Not started",
            table,
        ]
    )
    new, count, kept = ladder_layout.relayout(doc, price=_fake_price)
    assert (count, kept) == (1, 2)
    assert new.count("| Rank ") == 2 and new.split("## Step 3")[1].count("| Rank ") == 0
    phases = "\n\n".join(
        ["### Phase 4: Written", "**Status:** Not started", table]
        + ["### Phase 5: Later", "**Status:** Not started", table]
    )
    new, count, kept = ladder_layout.relayout(
        phases, price=_fake_price, phase_written=lambda p: p == "4"
    )
    assert (count, kept) == (1, 1)
    assert new.split("### Phase 5")[0].count("| Rank ") == 1


def test_relayout_leaves_a_table_it_does_not_know() -> None:
    odd = RANKED_TABLE.replace(
        "| Thinking      | —                 | On ", "| Speed         | —                 | On ", 1
    )
    assert ladder_layout.relayout(odd) == (odd, 0, 0)
    other = "| Item | Cost |\n| --- | --- |\n| EIN | $0 |\n"
    assert ladder_layout.relayout(other) == (other, 0, 0)


def test_relayout_command_prices_from_the_catalog_and_checks(tmp_path: Path) -> None:
    table = RANKED_TABLE[RANKED_TABLE.index("| Rank") :]
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text(
        f"### Phase 4: Written\n\n{table}\n### Phase 5: Later\n\n{table}", encoding="utf-8"
    )
    (tmp_path / "phase04-roadmap.md").write_text("# Phase 4\n", encoding="utf-8")
    before = roadmap.read_text(encoding="utf-8")
    check = CliRunner().invoke(cli, ["relayout", "--check", str(roadmap)])
    assert check.exit_code == 1 and "1 converted, 1 kept" in check.output
    assert roadmap.read_text(encoding="utf-8") == before
    done = CliRunner().invoke(cli, ["relayout", str(roadmap)])
    assert done.exit_code == 0, done.output
    after = roadmap.read_text(encoding="utf-8")
    later = after.split("### Phase 5")[1]
    assert "| Rank " in after.split("### Phase 5")[0] and "| Rank " not in later
    assert "/1M" in later
    again = CliRunner().invoke(cli, ["relayout", "--check", str(roadmap)])
    assert again.exit_code == 0 and "0 converted, 1 kept" in again.output


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
