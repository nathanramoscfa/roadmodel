"""Measured output tokens per effort: the measuring script and the scorer.

update/measure_effort_tokens.py runs every ladder model through a fixed
probe set at each effort its lane can set, tops up the noisy efforts, and
writes docs/effort-tokens.json; the scorer prices a model at an effort by
that measurement (scoring.token_use: measured, else derived from the model's
measured efforts, else the uniform table), scaling only the output share of
its blended price (scoring.effort_price).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from roadmodel import scoring

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import measure_effort_tokens as met  # noqa: E402
import supersede  # noqa: E402

SHA = "test-sha"


def _run(mid: str, level: str, probe: str, tokens: int | None, **kw: Any) -> dict[str, Any]:
    return {
        "key": f"{mid}|{level}|{probe}|{kw.get('sample', 0)}",
        "model_id": mid,
        "level": level,
        "lane": kw.get("lane", "codex"),
        "probe": probe,
        "sample": kw.get("sample", 0),
        "output_tokens": tokens,
        "error": kw.get("error"),
        "truncated": False,
        "probe_set_sha256": kw.get("sha", SHA),
    }


def _all_probes(mid: str, level: str, tokens: int, **kw: Any) -> list[dict[str, Any]]:
    return [_run(mid, level, p, tokens, **kw) for p, _ in met.PROBES]


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return met.summarize(runs, sha=SHA, skipped={}, generated_at="t", samples=1)


def test_the_multiplier_is_the_mean_over_the_median_model_at_high() -> None:
    runs = (
        _all_probes("a", "low", 100)
        + _all_probes("a", "high", 200)
        + _all_probes("b", "high", 400)
        + _all_probes("b", "max", 1200)
        + _all_probes("c", "medium", 300)
        + _all_probes("c", "high", 600)
    )
    doc = _summary(runs)
    assert doc["reference"] == {"level": "high", "mean_output_tokens": 400.0, "models": 3}
    assert doc["models"]["a"]["levels"]["low"]["multiplier"] == 0.25
    assert doc["models"]["b"]["levels"]["high"]["multiplier"] == 1.0
    assert doc["models"]["b"]["levels"]["max"]["multiplier"] == 3.0
    assert list(doc["models"]["c"]["levels"]) == ["medium", "high"]


def test_each_probe_weighs_the_same_whatever_its_samples() -> None:
    runs = _all_probes("a", "high", 100) + _all_probes("a", "low", 100)
    # A second sample of one probe moves that probe's mean, not its weight.
    runs.append(_run("a", "high", met.PROBES[0][0], 900, sample=1))
    doc = _summary(runs)
    n = len(met.PROBES)
    assert doc["models"]["a"]["levels"]["high"]["mean_output_tokens"] == round(
        (500 + 100 * (n - 1)) / n, 1
    )


def test_a_level_short_of_its_probes_or_a_lone_level_is_left_out() -> None:
    few = [_run("a", "low", p, 50) for p, _ in met.PROBES[:2]]
    failed = [_run("a", "max", p, None, error="boom") for p, _ in met.PROBES]
    runs = (
        _all_probes("a", "high", 100)
        + few
        + failed
        + _all_probes("b", "high", 100)  # one level only: no ratio to read
        + _all_probes("c", "high", 100)
        + _all_probes("c", "low", 50)
    )
    doc = _summary(runs)
    assert "b" not in doc["models"]
    assert "a" not in doc["models"]  # only `high` survives for it
    assert list(doc["models"]["c"]["levels"]) == ["low", "high"]


def test_a_rerun_replaces_a_failed_run_and_old_probe_sets_are_ignored() -> None:
    runs = _all_probes("a", "high", 100) + _all_probes("a", "low", 10, sha="old")
    runs += [_run("a", "low", p, None, error="x") for p, _ in met.PROBES]
    runs += [_run("a", "low", p, 50) for p, _ in met.PROBES]
    doc = _summary(runs)
    assert doc["models"]["a"]["levels"]["low"]["mean_output_tokens"] == 50.0


def test_no_reference_level_is_an_error() -> None:
    with pytest.raises(ValueError, match="reference"):
        _summary(_all_probes("a", "low", 10) + _all_probes("a", "max", 20))


def _bench(**models: dict[str, Any]) -> dict[str, Any]:
    return {"models": models}


def _ladder_catalog() -> dict[str, Any]:
    ids = ["claude-fable-5.1", "gpt-6-luna", "grok-4.7", "kimi-k3", "gemini-3-pro", "haiku"]
    return {
        "models": [
            *({"id": mid, "input_price_per_1m": 2.0, "output_price_per_1m": 10.0} for mid in ids),
            {"id": "old", "superseded_by": "grok-4.7"},
        ],
        "access_methods": [
            {
                "id": "claude-code",
                "effort_levels": list(met.LEVELS),
                "effort_levels_by_model": {"claude-fable-5.1": list(met.LEVELS)},
            },
            {"id": "codex-cli", "effort_levels": [*met.LEVELS, "ultra"]},
        ],
    }


def _aa_row(creator: str, **kw: Any) -> dict[str, Any]:
    return {
        "aa_creator": creator,
        "evaluations": {"artificial_analysis_intelligence_index": 40.0},
        **kw,
    }


def test_the_plan_runs_every_ladder_model_at_each_level_its_lane_sets() -> None:
    """A ladder can show a model at any level of its dial (a lower rung, a
    phase session's top), so each runs at every level its lane can set, not
    only the efforts AA measured (2026-10-30: Gemini 4 Argon read `not
    measured` at low, medium and max)."""
    bench = _bench(
        **{
            "claude-fable-5.1": _aa_row("Anthropic", aa_effort="max"),
            "gpt-6-luna": _aa_row("OpenAI", aa_effort="max"),
            "grok-4.7": _aa_row("xAI", aa_effort="high"),
            "kimi-k3": _aa_row("Moonshot"),
            "gemini-3-pro": _aa_row("Google"),
            "haiku": _aa_row("Anthropic"),  # no dial on Claude Code
            "old": _aa_row("xAI"),  # superseded: not a ladder model
        }
    )
    routes = {
        "grok-4.7": ("x-ai/grok-4.7", ["xhigh", "high", "low"]),
        "kimi-k3": ("moonshotai/kimi-k3", ["high"]),
    }
    jobs, skipped = met.plan(
        bench, _ladder_catalog(), samples=2, models=None, levels=None, routes=routes
    )
    lanes = {(j.model_id, j.lane, j.target) for j in jobs}
    assert lanes == {
        ("claude-fable-5.1", "claude-code", "claude-fable-5-1"),
        ("gpt-6-luna", "codex", "gpt-6-luna"),
        ("grok-4.7", "openrouter", "x-ai/grok-4.7"),
    }
    assert {j.level for j in jobs if j.model_id == "claude-fable-5.1"} == set(met.LEVELS)
    assert {j.level for j in jobs if j.model_id == "gpt-6-luna"} == set(met.LEVELS)
    assert {j.level for j in jobs if j.model_id == "grok-4.7"} == {"low", "high", "xhigh"}
    assert {"kimi-k3", "gemini-3-pro", "haiku"} <= set(skipped)
    assert skipped["grok-4.7@max"] == "OpenRouter cannot set this effort"
    assert "old" not in skipped and all(j.model_id != "old" for j in jobs)
    assert len(jobs) == (5 + 5 + 3) * len(met.PROBES) * 2
    samples = [j.sample for j in jobs]
    assert samples == sorted(samples)  # every first sample before any second


def test_only_codex_carries_the_no_commands_line() -> None:
    # xAI refuses a prompt carrying it; the other lanes run with no tools.
    assert met.CODEX_PREAMBLE in met._prompt("dice", "codex")
    assert met.CODEX_PREAMBLE not in met._prompt("dice", "openrouter")
    assert met.CODEX_PREAMBLE not in met._prompt("dice", "claude-code")


def test_the_scorer_reads_measured_multipliers_and_falls_back() -> None:
    measured = {"m": {"medium": 1.9}}
    assert scoring.token_multiplier("m", "medium", measured) == 1.9
    assert (
        scoring.token_multiplier("m", "high", measured) == scoring.EFFORT_TOKEN_MULTIPLIER["high"]
    )
    assert scoring.token_multiplier("x", "low", measured) == scoring.EFFORT_TOKEN_MULTIPLIER["low"]


def test_frontier_price_scales_the_output_share_by_the_measured_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scoring, "effort_token_multipliers", lambda: {"m": {"medium": 2.0}})
    c = scoring.Candidate(
        model_id="m",
        model_name="M",
        provider="p",
        platform_id="x",
        platform_name="X",
        funding="subscription",
        pool_state="headroom",
        quality=50.0,
        quality_source="aa",
        letter="A",
        requirement=50.0,
        requirement_penalty=0.0,
        blended_price_usd=4.0,
        output_share=0.5,
        scarcity=0.35,
        effort="medium",
        effort_multiplier=2.0,
        effective_cost_usd=2.1,
        cost_decades=1.0,
        cost_penalty=1.0,
        score=1.0,
        evidence_level="medium",
    )
    # $2 of input stays; $2 of output doubles: $6, not the whole $4 doubled.
    assert scoring.frontier_price(c) == 6.0


def test_the_committed_measurements_are_well_formed() -> None:
    doc = json.loads((REPO_ROOT / "docs" / "effort-tokens.json").read_text())
    bench = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]
    # A retired model's row leaves the benchmark layer, but its measurement
    # stays: it is part of the reference every multiplier is taken over.
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    retired = {mid for mid, t in supersede.base_tags(selector).items() if t.retired}
    assert doc["schema_version"] == met.SCHEMA_VERSION
    assert doc["probe_set_sha256"] == met.probe_set_sha256(), "probes changed: re-measure"
    assert doc["models"], "no model measured"
    for mid, row in doc["models"].items():
        assert mid in bench or mid in retired, mid
        assert len(row["levels"]) > 1, mid
        for level, v in row["levels"].items():
            assert level in scoring.EFFORT_LADDER, (mid, level)
            assert v["multiplier"] > 0, (mid, level)
    # The bundled loader reads every measured level.
    loaded = scoring.effort_token_multipliers.__wrapped__()
    assert set(loaded) == set(doc["models"])
    # Derived levels fill the gaps a ladder can show, never a measured one.
    for mid, levels in doc.get("derived", {}).items():
        assert not set(levels) & set(doc["models"].get(mid, {}).get("levels", {})), mid
        assert all(lv in scoring.EFFORT_LADDER and v > 0 for lv, v in levels.items()), mid
    for mid, levels in doc.get("settable", {}).items():
        assert levels and all(lv in scoring.EFFORT_LADDER for lv in levels), mid


def test_openrouter_models_are_scaled_by_the_measured_lane_factor() -> None:
    # "s" runs on Codex and, as calibration, on OpenRouter at twice the tokens:
    # the lane factor is 0.5, and the OpenRouter-only model "o" is halved.
    runs = _all_probes("s", "low", 100) + _all_probes("s", "high", 200)
    runs += [
        {**r, "key": r["key"] + "|calibration", "lane": "openrouter", "calibration": True}
        for r in _all_probes("s", "low", 200) + _all_probes("s", "high", 400)
    ]
    runs += _all_probes("o", "low", 200, lane="openrouter")
    runs += _all_probes("o", "high", 400, lane="openrouter")
    doc = _summary(runs)
    assert doc["lanes"]["openrouter"] == {"factor": 0.5, "pairs": 2}
    assert doc["reference"]["mean_output_tokens"] == 200.0
    assert doc["models"]["o"]["levels"]["high"]["mean_output_tokens"] == 400.0  # raw
    assert doc["models"]["o"]["levels"]["high"]["multiplier"] == 1.0  # scaled
    assert doc["models"]["s"]["levels"]["low"]["multiplier"] == 0.5
    assert "|calibration" not in "".join(doc["models"])


def _cand(mid: str, level: str | None, *, platform: str = "x", penalty: float = 0.0) -> Any:
    return scoring.Candidate(
        model_id=mid,
        model_name=mid,
        provider="p",
        platform_id=platform,
        platform_name=platform,
        funding="subscription",
        pool_state="headroom",
        quality=50.0,
        quality_source="aa",
        letter="A",
        requirement=50.0,
        requirement_penalty=penalty,
        blended_price_usd=1.0,
        output_share=0.5,
        scarcity=0.35,
        effort=level or "medium",
        effort_multiplier=1.0,
        effective_cost_usd=0.35,
        cost_decades=1.0,
        cost_penalty=1.0,
        score=1.0,
        evidence_level=level,
    )


def test_quality_may_read_its_own_model_at_a_higher_effort() -> None:
    """The frontier can drop a model's own higher efforts (another model's
    cheaper point out-scores them on the AA Index); QUALITY still sees them."""
    top = scoring.FrontierPoint(_cand("g", "low"), 30.0, 1.0)
    settings = [
        _cand("g", "low"),
        _cand("g", "medium"),
        _cand("g", "high"),
        _cand("g", "xhigh", penalty=3.0),  # misses the bar
        _cand("g", "high", platform="y"),  # another platform
        _cand("h", "max"),  # another model
    ]
    got = scoring._higher_efforts(top, settings, {})
    assert [(p.candidate.model_id, p.candidate.evidence_level) for p in got] == [
        ("g", "medium"),
        ("g", "high"),
    ]
    assert (
        scoring._higher_efforts(scoring.FrontierPoint(_cand("g", None), 30.0, 1.0), settings, {})
        == []
    )


def test_a_higher_effort_never_reads_fewer_tokens() -> None:
    assert met.monotone([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]
    assert met.monotone([2.0, 1.0, 3.0]) == [1.5, 1.5, 3.0]
    assert met.monotone([3.0, 2.0, 1.0]) == [2.0, 2.0, 2.0]
    runs = _all_probes("a", "low", 220) + _all_probes("a", "medium", 200)
    runs += _all_probes("a", "high", 400)
    doc = _summary(runs)
    levels = doc["models"]["a"]["levels"]
    assert levels["low"]["mean_output_tokens"] == 220.0  # raw kept
    assert levels["low"]["multiplier"] == levels["medium"]["multiplier"] == 0.525


def test_unmeasured_lists_new_ladder_efforts_but_not_explained_gaps() -> None:
    bench = _bench(
        **{
            "claude-fable-5.1": _aa_row("Anthropic"),
            "gpt-6-luna": _aa_row("OpenAI"),
            "grok-4.7": _aa_row("xAI"),
            "kimi-k3": _aa_row("Moonshot"),
            "haiku": _aa_row("Anthropic"),  # no dial: nothing to measure
        }
    )
    doc = {
        "models": {
            "claude-fable-5.1": {"levels": {lv: {} for lv in met.LEVELS}},
            "gpt-6-luna": {"levels": {"low": {}, "high": {}}},
            "grok-4.7": {"levels": {"low": {}, "high": {}}},
        },
        # A derived figure is not a measurement.
        "derived": {"gpt-6-luna": {"medium": 0.5}},
        "unmeasured": {
            "kimi-k3": "no lane serves it",
            **{f"grok-4.7@{lv}": "OpenRouter cannot set this effort" for lv in ("medium", "max")},
        },
    }
    assert met.unmeasured(bench, _ladder_catalog(), doc) == {
        "gpt-6-luna": ["medium", "xhigh", "max"],
        "grok-4.7": ["xhigh"],
    }


def test_the_benchmark_cron_keeps_one_issue_for_unmeasured_efforts() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-benchmarks.yml").read_text()
    assert "python update/measure_effort_tokens.py --unmeasured" in wf
    assert "chore(effort-tokens): model efforts not yet token-measured" in wf


def test_a_narrowed_run_keeps_every_models_skip_reason() -> None:
    src = (UPDATE_DIR / "measure_effort_tokens.py").read_text()
    assert "plan(bench, catalog, samples=1, models=None, levels=None, routes=routes)" in src
    assert "skipped=reasons," in src


# --------------------------------------------------------------------------- #
# 2026-10-30: price accuracy at the lowest cost — a noise measure and top-ups
# for the noisy efforts only, derived levels where a lane cannot measure, and
# a price that scales only the output share.
# --------------------------------------------------------------------------- #


def test_ci90_is_the_spread_of_each_probes_samples_relative_to_the_mean() -> None:
    assert met.ci90({"a": [100], "b": [300]}) is None  # no probe sampled twice
    # Probe a's two samples differ by 20 (variance 200, its mean's 100); over
    # two probes the mean's variance is 100 / 4 = 25, so a standard error of 5
    # on a mean of 200.
    got = met.ci90({"a": [90, 110], "b": [300]})
    assert got == pytest.approx(met.Z90 * 5 / 200)


def test_a_top_up_reruns_only_the_noisy_efforts() -> None:
    """More samples where the price is not known to within the target, up to
    the cap; a steady effort or one at the cap is left alone."""
    probes = [p for p, _ in met.PROBES]
    runs = []
    for i, p in enumerate(probes):
        # Steady: every probe reads 100 twice. Noisy: 50 and 150.
        runs += [_run("m", "low", p, 100, sample=s) for s in (0, 1)]
        runs += [_run("m", "max", p, 50 if s else 150, sample=s) for s in (0, 1)]
        runs[-1]["key"] += ""
        del i
    for r in runs:
        r["key"] = f"{r['model_id']}|{r['level']}|{r['probe']}|{r['sample']}"
        r["target"] = "m-target"
    catalog = {"models": [{"id": "m", "input_price_per_1m": 1.0, "output_price_per_1m": 5.0}]}
    doc = {"models": {"m": {"levels": {"low": {"multiplier": 0.5}, "max": {"multiplier": 2.0}}}}}
    jobs = met.topup(runs, doc, catalog, sha=SHA, target=0.10, max_samples=6)
    assert {j.level for j in jobs} == {"max"}
    assert {j.target for j in jobs} == {"m-target"} and {j.lane for j in jobs} == {"codex"}
    assert {j.sample for j in jobs} == {2, 3, 4, 5}  # grown to the cap of 6
    assert {j.probe for j in jobs} == set(probes)
    # At the cap, or within the target, nothing more runs.
    assert met.topup(runs, doc, catalog, sha=SHA, target=0.10, max_samples=2) == []
    assert met.topup(runs, doc, catalog, sha=SHA, target=1.0, max_samples=6) == []


def test_the_output_share_is_what_the_tokens_move() -> None:
    model = {"input_price_per_1m": 4.0, "output_price_per_1m": 20.0}
    assert met.output_share(model, 1.0) == pytest.approx(20 / 32)
    # At 8.4x the tokens almost the whole price is output.
    assert met.output_share(model, 8.4) == pytest.approx(168 / 180)
    assert scoring.output_share(model) == pytest.approx(20 / 32)


def test_derived_levels_read_between_or_by_the_median_ratio() -> None:
    measured = {
        "a": {"low": 0.5, "high": 2.0},
        "b": {"low": 0.4, "medium": 0.6, "high": 1.0, "max": 3.0},
        "c": {"high": 1.0, "max": 2.0},
    }
    derived, typical = met.derive(
        measured, {"a": list(met.LEVELS), "c": ["low", "high", "max"], "z": ["high"]}
    )
    # Between two measured levels: the geometric midpoint.
    assert derived["a"]["medium"] == pytest.approx(1.0)
    # Above them all: the nearest level times the median ratio of the others
    # measured at both (max/high: b 3, c 2).
    assert derived["a"]["max"] == pytest.approx(5.0)
    # Only the levels asked for; never a measured one.
    assert set(derived["c"]) == {"low"} and "xhigh" not in derived["a"]
    # A model with no measurement reads the typical model's.
    assert derived["z"] == {"high": typical["high"]}
    assert typical["high"] == 1.0


def test_the_summary_records_settable_levels_and_derives_the_gaps() -> None:
    runs = _all_probes("a", "low", 100) + _all_probes("a", "high", 200)
    runs += _all_probes("b", "low", 100) + _all_probes("b", "medium", 150)
    runs += _all_probes("b", "high", 200)
    doc = met.summarize(
        runs,
        sha=SHA,
        skipped={},
        generated_at="t",
        samples=1,
        settable={"a": ["low", "medium", "high"]},
        derive_for={"a": ["low", "medium", "high"], "n": ["high"]},
    )
    assert doc["settable"] == {"a": ["low", "medium", "high"]}
    assert set(doc["derived"]["a"]) == {"medium"}
    assert doc["derived"]["n"] == {"high": 1.0}
    assert doc["models"]["a"]["levels"]["low"]["ci90"] is None  # one sample a probe


def test_token_use_is_measured_then_derived_then_uniform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scoring, "effort_token_multipliers", lambda: {"m": {"high": 0.7}})
    monkeypatch.setattr(scoring, "derived_token_multipliers", lambda: {"m": {"max": 3.1}})
    assert scoring.token_use("m", "high") == (0.7, True)
    assert scoring.token_use("m", "max") == (3.1, False)
    assert scoring.token_use("m", "low") == (scoring.EFFORT_TOKEN_MULTIPLIER["low"], False)
    assert scoring.token_multiplier("m", "max") == 3.1


def test_effort_price_keeps_the_input_and_scales_the_output() -> None:
    """Opus 5.5 ($4/$20, blended $8) at 8.447x a typical model's output read
    $67.58 when the multiplier scaled the whole blended price; the input it
    reads does not grow with its effort (2026-10-30)."""
    opus = {"input_price_per_1m": 4.0, "output_price_per_1m": 20.0}
    blended = scoring.blended_price(opus)
    share = scoring.output_share(opus)
    assert round(scoring.effort_price(blended, share, 8.447), 2) == 45.23
    assert scoring.effort_price(blended, share, 1.0) == pytest.approx(blended)
    # A terse model is not discounted on its input.
    assert scoring.effort_price(blended, share, 0.0) == pytest.approx(3.0)


def test_a_dial_less_surface_stops_at_the_models_own_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antigravity documents no dial, so a phase session's Quality went to
    `max` for Gemini 4 Argon, a level its API does not offer (OpenRouter takes
    low, medium and high): the model's own levels cap it."""
    monkeypatch.setattr(scoring, "settable_levels", lambda: {"g": ["low", "medium", "high"]})
    c = _cand("g", "high", platform="antigravity")
    catalog: dict[str, Any] = {"access_methods": [{"id": "antigravity"}]}
    assert scoring._deepest_level(c, catalog) == "high"
    assert scoring._step_down(c, "high", 2, catalog) == "low"
    other = _cand("x", "high", platform="antigravity")
    assert scoring._deepest_level(other, catalog) == "max"  # nothing known: the whole ladder


def _aa_bench(**levels: dict[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mid, by in levels.items():
        top = max(by, key=scoring.EFFORT_LADDER.index)
        out[mid] = {
            "aa_effort": top,
            "evaluations": {"artificial_analysis_intelligence_index": by[top]},
            "effort_variants": {
                lv: {"evaluations": {"artificial_analysis_intelligence_index": v}}
                for lv, v in by.items()
                if lv != top
            },
        }
    return out


def test_an_unmeasured_aa_effort_is_estimated_from_the_measured_ones() -> None:
    bench = _aa_bench(
        a={"low": 40.0, "medium": 45.0, "high": 48.0, "max": 52.0},
        b={"low": 30.0, "medium": 37.0, "high": 40.0, "max": 46.0},
        c={"low": 20.0, "medium": 23.0, "high": 25.0, "max": 31.0},
        argon={"high": 50.0},
        gap={"low": 30.0, "max": 40.0},
    )
    est = scoring.estimated_aa_index
    # A level away: the median shift of the models measured at both.
    assert est(bench, "argon", "medium") == 47.0  # shifts -3, -3, -2 → -3
    assert est(bench, "argon", "max") == 56.0  # shifts +4, +6, +6 → +6
    # Between two measured efforts: read between them.
    assert est(bench, "gap", "medium") == 32.5
    assert est(bench, "gap", "xhigh") == 37.5
    # Nothing measured, or nobody measured at both: no estimate.
    assert est(bench, "missing", "high") is None
    assert est(_aa_bench(solo={"high": 50.0}), "solo", "max") is None


def test_with_nothing_new_to_measure_the_top_ups_still_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run after every level is measured still tops up the noisy ones (the
    first resumed run stopped at an empty first round, 2026-10-30)."""
    calls: list[set[str] | None] = []

    def topup(*_: Any, **kw: Any) -> list[Any]:
        calls.append(kw.get("models"))
        return []

    monkeypatch.setattr(met, "openrouter_routes", lambda: {})
    monkeypatch.setattr(met, "plan", lambda *a, **k: ([], {}))
    monkeypatch.setattr(met, "topup", topup)
    monkeypatch.setattr(met, "summarize", lambda *a, **k: {"models": {}})
    monkeypatch.setattr(met, "_keychain", lambda name: None)
    out = tmp_path / "out.json"
    assert met.main(["--runs", str(tmp_path / "runs.jsonl"), "--out", str(out)]) == 0
    assert len(calls) == 1
    # Only ladder models are topped up, not a superseded one still in the runs.
    assert calls[0] and "claude-opus-5-5" in calls[0]


def test_the_reference_is_kept_while_the_probe_set_is_unchanged() -> None:
    """The reference is where a model's price equals its list price; a running
    median over every measured model nearly doubled once the budget models
    were measured at high (2026-10-30), which would have moved every price."""
    runs = _all_probes("a", "low", 100) + _all_probes("a", "high", 200)
    runs += _all_probes("verbose", "low", 900) + _all_probes("verbose", "high", 1800)
    runs += _all_probes("loud", "low", 900) + _all_probes("loud", "high", 2000)
    kept = {"level": "high", "mean_output_tokens": 200.0, "models": 1}
    doc = met.summarize(runs, sha=SHA, skipped={}, generated_at="t", samples=1, reference=kept)
    assert doc["reference"] == kept
    assert doc["models"]["a"]["levels"]["high"]["multiplier"] == 1.0
    assert doc["models"]["verbose"]["levels"]["high"]["multiplier"] == 9.0
    # Without one, the median of the measured models.
    assert _summary(runs)["reference"]["mean_output_tokens"] == 1800.0
    src = (UPDATE_DIR / "measure_effort_tokens.py").read_text()
    assert 'previous.get("probe_set_sha256") == sha' in src
