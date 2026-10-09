"""Measured output tokens per effort: the measuring script and the scorer.

update/measure_effort_tokens.py runs each model AA measured at several
efforts through a fixed probe set and writes docs/effort-tokens.json; the
scorer prices a model at an effort by that measurement
(scoring.token_multiplier), falling back to the uniform table.
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


def test_the_plan_routes_each_model_to_its_lane_first_sample_first() -> None:
    bench = _bench(
        **{
            "claude-fable-5.1": {
                "aa_creator": "Anthropic",
                "aa_effort": "max",
                "effort_variants": {"low": {}},
            },
            "gpt-6-luna": {
                "aa_creator": "OpenAI",
                "aa_effort": "max",
                "effort_variants": {"low": {}},
            },
            "grok-4.7": {
                "aa_creator": "xAI",
                "aa_effort": "high",
                "effort_variants": {"low": {}, "xhigh": {}},
            },
            "kimi-k3": {
                "aa_creator": "Moonshot",
                "aa_effort": "max",
                "effort_variants": {"low": {}},
            },
            "gemini-3-pro": {
                "aa_creator": "Google",
                "aa_effort": "high",
                "effort_variants": {"low": {}},
            },
            "haiku": {"aa_creator": "Anthropic"},  # AA names no effort
        }
    )
    routes = {
        "grok-4.7": ("x-ai/grok-4.7", ["xhigh", "high", "low"]),
        "kimi-k3": ("moonshotai/kimi-k3", ["high"]),
    }
    jobs, skipped = met.plan(bench, samples=2, models=None, levels=None, routes=routes)
    lanes = {(j.model_id, j.lane, j.target) for j in jobs}
    assert lanes == {
        ("claude-fable-5.1", "claude-code", "claude-fable-5-1"),
        ("gpt-6-luna", "codex", "gpt-6-luna"),
        ("grok-4.7", "openrouter", "x-ai/grok-4.7"),
    }
    assert {j.level for j in jobs if j.model_id == "grok-4.7"} == {"low", "high", "xhigh"}
    assert set(skipped) == {"kimi-k3", "gemini-3-pro"}
    # Fable and Luna at low and max, Grok at three levels: each probe twice.
    assert len(jobs) == (2 + 2 + 3) * len(met.PROBES) * 2
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


def test_frontier_price_uses_the_measured_multiplier(monkeypatch: pytest.MonkeyPatch) -> None:
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
        scarcity=0.35,
        effort="medium",
        effort_multiplier=2.0,
        effective_cost_usd=2.8,
        cost_decades=1.0,
        cost_penalty=1.0,
        score=1.0,
        evidence_level="medium",
    )
    assert scoring.frontier_price(c) == 8.0


def test_the_committed_measurements_are_well_formed() -> None:
    doc = json.loads((REPO_ROOT / "docs" / "effort-tokens.json").read_text())
    bench = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]
    assert doc["schema_version"] == met.SCHEMA_VERSION
    assert doc["probe_set_sha256"] == met.probe_set_sha256(), "probes changed: re-measure"
    assert doc["models"], "no model measured"
    for mid, row in doc["models"].items():
        assert mid in bench, mid
        assert len(row["levels"]) > 1, mid
        for level, v in row["levels"].items():
            assert level in scoring.EFFORT_LADDER, (mid, level)
            assert v["multiplier"] > 0, (mid, level)
    # The bundled loader reads every measured level.
    loaded = scoring.effort_token_multipliers.__wrapped__()
    assert set(loaded) == set(doc["models"])


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


def test_unmeasured_lists_new_efforts_but_not_explained_gaps() -> None:
    bench = _bench(
        a={"aa_effort": "max", "effort_variants": {"low": {}, "high": {}}},
        b={"aa_effort": "high", "effort_variants": {"low": {}}},
        c={"aa_effort": "high", "effort_variants": {"low": {}, "xhigh": {}}},
        d={"aa_effort": "high"},  # one effort: nothing to compare
    )
    doc = {
        "models": {
            "a": {"levels": {"low": {}, "high": {}}},
            "c": {"levels": {"low": {}, "high": {}}},
        },
        "unmeasured": {"b": "no lane serves it", "c@xhigh": "OpenRouter cannot set this effort"},
    }
    assert met.unmeasured(bench, doc) == {"a": ["max"]}


def test_the_benchmark_cron_keeps_one_issue_for_unmeasured_efforts() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-benchmarks.yml").read_text()
    assert "python update/measure_effort_tokens.py --unmeasured" in wf
    assert "chore(effort-tokens): model efforts not yet token-measured" in wf


def test_a_narrowed_run_keeps_every_models_skip_reason() -> None:
    src = (UPDATE_DIR / "measure_effort_tokens.py").read_text()
    assert "skipped=plan(bench, samples=1, models=None, levels=None, routes=routes)[1]" in src
