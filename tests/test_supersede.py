"""The catalog's lifecycle rule (update/supersede.py) and what honours it.

A model is superseded when another model from the same maker costs the same or
less (blended), scores higher on the AA Intelligence Index, is rated at least
as high in every category, and is offered by every access method that offers
it. It is tagged at once, dropped from the recommender's candidates while the
successor is available, and retired 30 days later: it then leaves
docs/catalog.json (the website, the MCP catalog) but stays in the selector as
the record of what replaced it.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import supersede  # noqa: E402

TODAY = dt.date(2026, 9, 24)
CATS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")


def _model(
    mid: str, price_in: float, price_out: float, aa: float | None, letter: str = "A", **tier: str
) -> str:
    ratings = " ".join(f'tier-{c}="{tier.get(c.replace("-", "_"), letter)}"' for c in CATS)
    bench = f"AA Intelligence Index {aa}" if aa is not None else "none"
    return (
        f'<model id="{mid}" name="{mid.title()}"\n'
        f'       input-price-per-1m="${price_in:.2f}" output-price-per-1m="${price_out:.2f}"\n'
        f'       jurisdiction="us" {ratings}\n'
        f'       headline-benchmarks="{bench}" pricing-notes="" best-for=""/>'
    )


def _selector(models: list[str], methods: dict[str, tuple[str, list[str]]]) -> str:
    method_xml = "\n".join(
        f'<method id="{mid}" name="{mid}" provider="{prov}" supports-models="{",".join(ids)}"/>'
        for mid, (prov, ids) in methods.items()
    )
    return (
        '<model-options>\n<tier cost="high">\n'
        + "\n".join(models)
        + "\n</tier>\n</model-options>\n<access-methods>\n"
        + method_xml
        + "\n</access-methods>\n"
    )


BASE_METHODS = {
    "maker-api": ("maker", ["old", "new"]),
    "other-api": ("other", ["rival"]),
    "cursor": ("cursor", ["old", "new", "rival"]),
}


def _succ(
    models: list[str], methods: dict[str, tuple[str, list[str]]] = BASE_METHODS
) -> dict[str, str]:
    text = _selector(models, methods)
    return supersede.successors(text, supersede.parse_models(text, {}))


def test_a_newer_model_that_wins_on_every_count_supersedes() -> None:
    assert _succ([_model("old", 5, 25, 40), _model("new", 4, 20, 50)]) == {"old": "new"}


@pytest.mark.parametrize(
    ("new", "why"),
    [
        (_model("new", 6, 30, 50), "costs more"),
        (_model("new", 4, 20, 40), "scores the same"),
        (_model("new", 4, 20, 50, speed="D"), "rates lower in a category"),
        (_model("new", 4, 20, None), "has no AA Index"),
    ],
)
def test_no_supersession_unless_every_condition_holds(new: str, why: str) -> None:
    assert _succ([_model("old", 5, 25, 40, speed="C"), new]) == {}, why


def test_the_successor_must_run_everywhere_the_old_model_does() -> None:
    methods = dict(BASE_METHODS, only_old=("maker", ["old"]))
    assert _succ([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], methods) == {}


def test_a_benched_model_displaces_nothing() -> None:
    """A series keeps a recommendable model while its newest is unavailable."""
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    models = supersede.parse_models(text, {})
    assert supersede.successors(text, models) == {"old": "new"}
    assert supersede.successors(text, models, frozenset({"new"})) == {}


def test_the_availability_list_is_read_as_ids(tmp_path: Path) -> None:
    path = tmp_path / "model-availability.json"
    path.write_text('{"_note": "x", "unavailable": [{"id": "claude-fable-5"}, "gpt-x"]}')
    assert supersede.unavailable_ids(path) == frozenset({"claude-fable-5", "gpt-x"})
    assert supersede.unavailable_ids(tmp_path / "missing.json") == frozenset()


def test_only_the_same_maker_supersedes() -> None:
    assert _succ([_model("old", 5, 25, 40), _model("rival", 1, 2, 60)]) == {}


def _estimates(**rows: tuple[float, float]) -> dict[str, object]:
    return {"models": {mid: {"index": i, "band": b} for mid, (i, b) in rows.items()}}


def _succ_est(models: list[str], estimates: dict[str, object]) -> dict[str, str]:
    text = _selector(models, BASE_METHODS)
    return supersede.successors(text, supersede.parse_models(text, {}, estimates))


def test_an_unmeasured_successor_counts_its_estimate_less_half_its_band() -> None:
    """Claude Fable 5.2 (2026-11-16): cheaper than Fable 5.1, estimated well
    above it, but never measured while AA's measurements were frozen."""
    models = [_model("old", 5, 25, 40), _model("new", 4, 20, None)]
    assert _succ_est(models, _estimates(new=(42.0, 3.5))) == {"old": "new"}  # 40.2 > 40
    assert _succ_est(models, _estimates(new=(41.7, 3.5))) == {}  # 39.9: inside the margin
    assert _succ_est(models, _estimates(new=(42.0, 5.0))) == {}  # 39.5: a wider band
    assert _succ_est(models, {}) == {}


def test_a_measurement_overrides_the_estimate() -> None:
    models = [_model("old", 5, 25, 40), _model("new", 4, 20, 39)]
    assert _succ_est(models, _estimates(new=(60.0, 3.5))) == {}
    parsed = supersede.parse_models(
        _selector(models, BASE_METHODS), {}, _estimates(new=(60.0, 3.5))
    )
    assert {m.id: m.aa_estimate for m in parsed} == {"old": None, "new": None}


def test_an_estimate_never_stands_in_for_the_older_model() -> None:
    """The older model is superseded only against a figure of its own."""
    models = [_model("old", 5, 25, None), _model("new", 4, 20, 50)]
    assert _succ_est(models, _estimates(old=(30.0, 3.5))) == {}


def test_the_successor_with_the_best_standing_wins() -> None:
    models = [
        _model("old", 5, 25, 40),
        _model("measured", 4, 20, 45),
        _model("estimated", 4, 20, None),
    ]
    methods = dict(BASE_METHODS, **{"maker-api": ("maker", ["old", "measured", "estimated"])})
    methods["cursor"] = ("cursor", ["old", "measured", "estimated", "rival"])
    text = _selector(models, methods)
    est = _estimates(estimated=(50.0, 3.5))  # 48.2 beats the measured 45
    assert supersede.successors(text, supersede.parse_models(text, {}, est)) == {
        "old": "estimated",
        "measured": "estimated",
    }


@pytest.mark.parametrize("band", [3.5, 4.0, 5.0, 2.25])
def test_the_estimate_margin_is_the_pick_penalty(band: float) -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from roadmodel import scoring

    assert supersede.estimate_penalty(band) == scoring.estimate_penalty(band)


def test_near_misses_judge_with_the_committed_estimates_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog pass's targeted checks and the issue closer call
    live_near_misses without estimates; they must see what the rule sees."""
    methods = dict(BASE_METHODS, only_old=("maker", ["old"]))
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, None)], methods)
    path = tmp_path / "index-estimates.json"
    path.write_text(json.dumps(_estimates(new=(45.0, 3.5))))
    monkeypatch.setattr(supersede, "ESTIMATES_PATH", path)
    assert [n.line() for n in supersede.live_near_misses(text, {})] == [
        "NEAR-MISS old -> new: missing on only_old"
    ]
    assert supersede.live_near_misses(text, {}, {}) == []


def test_the_cli_reads_the_committed_estimates() -> None:
    estimates = supersede.load_estimates()
    assert supersede.ESTIMATES_PATH.name == "index-estimates.json"
    assert isinstance(estimates.get("models"), dict)
    assert supersede.load_estimates(REPO_ROOT / "no-such-file.json") == {}


def _plan(
    text: str, today: dt.date, base: dict[str, supersede.Tags] | None = None
) -> supersede.Plan:
    return supersede.plan(text, {}, today, base)


def test_the_clock_starts_on_first_supersession_and_retires_30_days_on() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    first = _plan(text, TODAY)
    assert first.newly == ["old"] and first.tags["old"] == supersede.Tags("new", "2026-09-24")
    tagged = supersede.apply(text, first)
    assert 'superseded-by="new" superseded-on="2026-09-24"' in tagged
    # The next day nothing moves; the date is kept.
    assert _plan(tagged, TODAY + dt.timedelta(days=1)).newly == []
    assert supersede.apply(tagged, _plan(tagged, TODAY + dt.timedelta(days=1))) == tagged
    # Thirty days on it retires, dated that day.
    later = TODAY + dt.timedelta(days=supersede.RETIRE_AFTER_DAYS)
    retire = _plan(tagged, later)
    assert retire.retired == ["old"] and retire.tags["old"].retired == later.isoformat()


def test_retirement_is_sticky_and_an_unretired_tag_clears() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    tagged = supersede.apply(text, _plan(text, TODAY))
    # The successor's price rises before retirement: the tag clears.
    pricier = tagged.replace(
        'input-price-per-1m="$4.00" output-price-per-1m="$20.00"',
        'input-price-per-1m="$9.00" output-price-per-1m="$40.00"',
    )
    cleared = _plan(pricier, TODAY + dt.timedelta(days=5))
    assert cleared.cleared == ["old"] and "old" not in cleared.tags
    assert "superseded-by" not in supersede.apply(pricier, cleared)
    # Once retired, it stays retired whatever changes.
    retire_day = TODAY + dt.timedelta(days=supersede.RETIRE_AFTER_DAYS)
    retired = supersede.apply(tagged, _plan(tagged, retire_day))
    pricier_after = retired.replace(
        'input-price-per-1m="$4.00" output-price-per-1m="$20.00"',
        'input-price-per-1m="$9.00" output-price-per-1m="$40.00"',
    )
    assert (
        _plan(pricier_after, TODAY + dt.timedelta(days=40)).tags["old"].retired
        == retire_day.isoformat()
    )


def test_a_tag_the_curation_pass_dropped_comes_back_with_its_date() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    committed = supersede.apply(text, _plan(text, TODAY))
    regenerated = text  # the curation pass re-emitted the element without its tags
    p = _plan(regenerated, TODAY + dt.timedelta(days=3), supersede.base_tags(committed))
    assert p.newly == [] and p.tags["old"].since == "2026-09-24"


def test_committed_tags_are_well_formed() -> None:
    """Stable invariants on the committed selector (not a re-run of the rule,
    which depends on the day's benchmarks): every tag names a real model,
    carries ISO dates, and retirement date is never earlier than supersession."""
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    models = {m.id: m for m in supersede.parse_models(text, {})}
    for m in models.values():
        if m.by is None:
            assert m.since is None and m.retired is None, m.id
            continue
        assert m.by in models and m.by != m.id, f"{m.id} superseded by unknown {m.by!r}"
        since = dt.date.fromisoformat(m.since or "")
        if m.retired:
            gap = (dt.date.fromisoformat(m.retired) - since).days
            assert gap >= 0, m.id


def _load(name: str) -> ModuleType:
    return importlib.reload(importlib.import_module(name))


def test_the_catalog_drops_a_retired_model_and_dates_a_superseded_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = _load("build_catalog")
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    tags = supersede.base_tags(text)
    live = sorted((k, v) for k, v in tags.items() if v.retired is None)
    if len(live) < 2:
        pytest.skip("the committed selector has too few superseded models to test with")
    victim, t = live[0]
    p = supersede.Plan(
        {**tags, victim: supersede.Tags(t.by, t.since, "2026-10-24")}, [], [], [victim]
    )
    selector = tmp_path / "model-selector.txt"
    selector.write_text(supersede.apply(text, p))
    monkeypatch.setattr(build, "SELECTOR_PATH", selector)
    catalog = build.build_catalog()
    ids = {m["id"] for m in catalog["models"]}
    assert victim not in ids
    assert all(victim not in m["supports_models"] for m in catalog["access_methods"])
    other = next(m for m in catalog["models"] if m["id"] == live[1][0])
    since = dt.date.fromisoformat(other["superseded_on"])
    assert other["retires_on"] == (since + dt.timedelta(days=build.RETIRE_AFTER_DAYS)).isoformat()


def test_the_recommender_never_sees_a_superseded_model_while_its_successor_is_available() -> None:
    from roadmodel import recommend

    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    live = sorted((k, v) for k, v in supersede.base_tags(text).items() if v.retired is None)
    if not live:
        pytest.skip("no superseded (unretired) model in the committed selector")
    old, t = live[0]
    element = re.compile(rf'<model\s+id="{re.escape(old)}"')
    kept = recommend._drop_superseded(text, None)
    assert not element.search(kept)
    assert all(old not in m.split(",") for m in re.findall(r'supports-models="([^"]*)"', kept))
    # Its successor benched at runtime: the superseded model is the fallback.
    fallback = recommend._drop_superseded(text, [t.by])
    assert element.search(fallback)
    # And an untagged model is untouched.
    untagged = next(m for m in supersede.parse_models(text, {}) if m.by is None)
    assert re.search(rf'<model\s+id="{re.escape(untagged.id)}"', kept)


def test_both_crons_run_the_rule() -> None:
    bench = (REPO_ROOT / ".github" / "workflows" / "update-benchmarks.yml").read_text()
    models = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert "python update/supersede.py --write" in bench
    assert "python update/supersede.py --write --base /tmp/base-selector.txt" in models
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert "superseded-by" in prompt and "retired-on" in prompt
    assert json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]


def test_the_retirement_day_retires_rerates_and_leaves_the_drift_check_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The benchmark cron's chain on the day a supersession turns 30 days old
    (it deadlocked every run from 2026-10-24): letters by rank are taken over
    the live models, so retiring one moves other models' letters, and the
    write that retires must re-derive them for derive_ratings.py --check."""
    derive = _load("derive_ratings")
    build = _load("build_catalog")
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    live = sorted((v.since, k) for k, v in supersede.base_tags(text).items() if v.retired is None)
    if not live:
        pytest.skip("no superseded (unretired) model in the committed selector")
    first_since = dt.date.fromisoformat(live[0][0])
    today = first_since + dt.timedelta(days=supersede.RETIRE_AFTER_DAYS)
    full = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())
    # The models the rule retires that day: a tagged model can also clear first.
    due = set(
        supersede.plan(
            text, full, today, None, supersede.unavailable_ids(), supersede.load_estimates()
        ).retired
    )
    if not due:
        pytest.skip("no model retires on the first leave date in the committed selector")
    benchmarks = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]

    selector = tmp_path / "model-selector.txt"
    selector.write_text(text)
    effort = tmp_path / "effort-ratings.json"
    monkeypatch.setattr(supersede, "EFFORT_RATINGS_PATH", effort)
    assert (
        supersede.main(["--write", "--today", today.isoformat(), "--selector", str(selector)]) == 0
    )
    out = capsys.readouterr().out
    after = selector.read_text()

    retired = {k for k, v in supersede.base_tags(after).items() if v.retired}
    assert due <= retired
    assert out.count("RETIRED ") == len(due)
    # The drift check: every live letter matches the derivation, and the
    # effort ratings were rewritten over the narrowed field.
    changes, _ = derive.plan_changes(after, benchmarks)
    assert changes == []
    assert effort.read_text() == derive.render_effort_ratings(
        derive.effort_letters(after, benchmarks)
    )
    # And it has left the catalog.
    monkeypatch.setattr(build, "SELECTOR_PATH", selector)
    ids = {m["id"] for m in build.build_catalog()["models"]}
    assert not retired & ids


def test_the_drift_check_still_catches_a_live_letter_off_the_derivation() -> None:
    derive = _load("derive_ratings")
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    benchmarks = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]
    live = derive.live_ids(text)
    derived = derive.derive({k: v for k, v in benchmarks.items() if k in live})["planning"]
    mid, row = next(iter(sorted(derived.items())))
    wrong = "D" if row["letter"] != "D" else "S"
    element = re.compile(rf'(<model\s+id="{re.escape(mid)}"[^>]*?tier-planning=")[SABCD]"')
    drifted, n = element.subn(rf'\g<1>{wrong}"', text, count=1)
    assert n == 1
    changes, _ = derive.plan_changes(drifted, benchmarks)
    assert {(c["id"], c["category"]) for c in changes} == {(mid, "planning")}


def test_series_parser_matches_roadmodel_package() -> None:
    from roadmodel import series

    pairs = [
        ("gpt-6-sol", "gpt-6.2-sol"),
        ("gpt-6-sol", "gpt-6-luna"),
        ("claude-fable-5.1", "claude-fable-5.2"),
        ("gemini-3-flash", "gemini-3.8-flash"),
        ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"),
        ("glm-4.5-air", "glm-5.3-flash"),
        ("glm-5.2", "glm-5.3"),
    ]
    for old_id, new_id in pairs:
        assert supersede.is_newer(old_id, new_id) == series.is_newer(old_id, new_id), (
            old_id,
            new_id,
        )


def test_aggregators_are_ignored_when_first_party_exists_and_checked_when_absent() -> None:
    fp_methods = {
        "openai-api": ("openai", ["gpt-6-sol", "gpt-6.1-sol"]),
        "cursor": ("cursor", ["gpt-6-sol"]),
    }
    fp_text = _selector(
        [_model("gpt-6-sol", 5, 25, 45), _model("gpt-6.1-sol", 4, 20, 52)],
        fp_methods,
    )
    assert supersede.successors(fp_text, supersede.parse_models(fp_text, {}), delisted={}) == {
        "gpt-6-sol": "gpt-6.1-sol"
    }
    assert supersede.near_misses(fp_text, supersede.parse_models(fp_text, {}), delisted={}) == []

    agg_methods = {
        "openrouter": ("openrouter", ["glm-5.1", "glm-5.2"]),
        "cursor": ("cursor", ["glm-5.1"]),
    }
    agg_text = _selector(
        [_model("glm-5.1", 2, 10, 35), _model("glm-5.2", 1, 5, 45)],
        agg_methods,
    )
    assert supersede.successors(agg_text, supersede.parse_models(agg_text, {}), delisted={}) == {}


def test_same_series_tolerance_transitive_head_and_immediate_retirement() -> None:
    methods = {"openai-api": ("openai", ["gpt-5.6-sol", "gpt-6-sol", "gpt-6.2-sol"])}
    # Newest costs more blended and has one lower category rating (long-context D vs S),
    # yet higher AA Index on the same series supersedes both 1-behind and 2-behind versions.
    m56 = _model("gpt-5.6-sol", 1, 5, 40, long_context="S")
    m60 = _model("gpt-6-sol", 2, 10, 47, long_context="S")
    m62 = _model(
        "gpt-6.2-sol",
        4,
        20,
        52,
        coding="S",
        planning="S",
        agentic="S",
        long_context="D",
        knowledge="S",
    )
    text = _selector([m56, m60, m62], methods)
    models = supersede.parse_models(text, {})
    assert supersede.successors(text, models, delisted={}) == {
        "gpt-5.6-sol": "gpt-6.2-sol",
        "gpt-6-sol": "gpt-6.2-sol",
    }
    p = supersede.plan(text, {}, TODAY, delisted={})
    # 5.6 is 2 versions behind (6 and 6.2) -> retires immediately; 6 is 1 behind -> waits 14 days.
    assert "gpt-5.6-sol" in p.retired
    assert p.tags["gpt-6-sol"].retired is None


def test_delisted_model_retires_immediately_with_maker_fallback() -> None:
    methods = {
        "zai-api": ("zai", ["glm-4.5-air"]),
        "openrouter": ("openrouter", ["glm-4.5-air", "glm-5.3-flash"]),
    }
    text = _selector(
        [_model("glm-4.5-air", 0.5, 2, 11.1), _model("glm-5.3-flash", 0.3, 1, 41.8)],
        methods,
    )
    p = supersede.plan(text, {}, TODAY, delisted={"zai": {"glm-4.5-air"}})
    assert p.tags["glm-4.5-air"] == supersede.Tags(
        "glm-5.3-flash", TODAY.isoformat(), TODAY.isoformat()
    )
    assert p.retired == ["glm-4.5-air"]
