"""Picks rank a model AA has not measured on roadmodel's estimate of its index.

roadmodel.estimate places a new model from its launch table (docs/
index-estimates.json). The scorer ranks it ESTIMATE_PENALTY below that
estimate: it takes a pick only by clearing a measured model by more than the
estimate's own uncertainty, and loses a near tie. A later version keeps its
previous version's other figures; a new series gets the index alone. Every
statistic read over the measured models is unchanged, and printed figures are
the estimate itself, marked ≈.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_successor import BENCH, CATALOG, CONTEXT, _model

from roadmodel import scoring

ROOT = Path(__file__).resolve().parents[1]
INDEX = scoring.FRONTIER_INDEX
P = scoring.ESTIMATE_PENALTY

# GPT-6.1 Sol is unmeasured; Gemini 9 Nova is a new series priced like it,
# reachable on Codex in this fixture so the funded pool holds it.
UNMEASURED = {k: v for k, v in BENCH.items() if k != "gpt-6.1-sol"}
WITH_NOVA = copy.deepcopy(CATALOG)
WITH_NOVA["models"].append(_model("gemini-9-nova", "Gemini 9 Nova", 2.0, 10.0, "google"))
WITH_NOVA["access_methods"][1]["supports_models"].append("gemini-9-nova")
PLANNING = scoring.Task("planning", "medium")


def _rows(estimates: dict[str, Any], bench: dict[str, Any] = UNMEASURED) -> dict[str, Any]:
    return scoring.with_estimates(
        scoring.inherit_unmeasured(bench, WITH_NOVA), WITH_NOVA, estimates
    )


def test_a_later_version_moves_its_copied_row_to_the_estimate() -> None:
    out = _rows({"gpt-6.1-sol": {"index": 55.0, "band": 3.5}})
    row = out["gpt-6.1-sol"]
    assert row["evaluations"][INDEX] == 55.0 - P
    # Every effort moves with it: GPT-6 Sol's medium sits 7.8 below its max.
    assert row["effort_variants"]["medium"]["evaluations"][INDEX] == round(55.0 - P - 7.8, 1)
    # Its other figures stay the previous version's, as before.
    assert row["evaluations"]["hle"] == BENCH["gpt-6-sol"]["evaluations"]["hle"]
    assert row["inherited_from"] == "gpt-6-sol"
    assert row["estimated"] == {"index": 55.0, "band": 3.5, "penalty": P}


def test_a_new_series_gets_the_index_at_its_top_effort_and_below_it() -> None:
    out = _rows({"gemini-9-nova": {"index": 40.0, "band": 3.5}})
    row = out["gemini-9-nova"]
    # Codex's dial tops at ultra, which the scorer reads as max.
    assert row["aa_effort"] == "max"
    assert row["evaluations"] == {INDEX: 40.0 - P}
    # Medium: the median max→medium shift of the measured models at both
    # (GPT-6 Sol −7.8, and GPT-6.1 Sol is unmeasured here, so −7.8 alone).
    assert row["effort_variants"] == {"medium": {"evaluations": {INDEX: round(40.0 - P - 7.8, 1)}}}
    assert "inherited_from" not in row


def test_a_measured_model_and_a_model_outside_the_catalog_ignore_an_estimate() -> None:
    out = _rows({"opus": {"index": 99.0}, "elsewhere": {"index": 50.0}})
    assert out["opus"] == BENCH["opus"]
    assert "elsewhere" not in out


def test_the_estimate_takes_the_frontier_point_only_beyond_the_penalty() -> None:
    measured = {**UNMEASURED, "gpt-6.1-sol": BENCH["gpt-6.1-sol"]}  # 51.8, same price as Nova

    def frontier_ids(est: float) -> set[str]:
        bench = _rows({"gemini-9-nova": {"index": est, "band": 3.5}}, measured)
        lad = scoring.ladder(PLANNING, CONTEXT, catalog=WITH_NOVA, benchmarks=bench)
        assert lad is not None
        return {p.candidate.model_id for p in lad.frontier}

    # 53.0 reads above GPT-6.1 Sol's 51.8, but within the penalty: it loses.
    assert "gemini-9-nova" not in frontier_ids(53.0)
    assert "gpt-6.1-sol" in frontier_ids(53.0)
    # 55.0 clears it by more than the penalty: it takes the point.
    assert "gemini-9-nova" in frontier_ids(55.0)


def test_printed_figures_are_the_estimate_marked_as_one() -> None:
    bench = _rows({"gemini-9-nova": {"index": 60.0, "band": 3.5}})
    assert scoring.ladder_aa(bench, "gemini-9-nova", "max") == (60.0, True)
    assert scoring.ladder_aa(bench, "gemini-9-nova", "medium") == (round(60.0 - 7.8, 1), True)
    lad = scoring.ladder(PLANNING, CONTEXT, catalog=WITH_NOVA, benchmarks=bench)
    assert lad is not None
    nova = next(p for p in lad.frontier if p.candidate.model_id == "gemini-9-nova")
    assert nova.candidate.aa_estimated and nova.aa_index == 60.0 - P
    assert scoring.aa_text(nova) == "≈60"
    assert "Gemini 9 Nova (AA ≈60" in scoring.render_ladder_table({"planning/medium": lad})


def test_the_scorer_reads_the_bundled_estimates_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scoring, "_load_benchmarks", lambda: UNMEASURED)
    monkeypatch.setattr(
        scoring, "_load_estimates", lambda: {"gemini-9-nova": {"index": 70.0, "band": 3.5}}
    )
    ranking = scoring.rank(PLANNING, CONTEXT, catalog=WITH_NOVA)
    nova = next(c for c in ranking.candidates if c.model_id == "gemini-9-nova")
    assert nova.aa_estimated and nova.aa_inherited_from is None
    sol = next(c for c in ranking.candidates if c.model_id == "gpt-6.1-sol")
    assert not sol.aa_estimated and sol.aa_inherited_from == "gpt-6-sol"


def test_the_estimates_change_no_statistic_over_the_measured_models() -> None:
    catalog = json.loads((ROOT / "docs" / "catalog.json").read_text(encoding="utf-8"))
    bench = json.loads((ROOT / "docs" / "benchmarks.json").read_text(encoding="utf-8"))["models"]
    estimates = json.loads((ROOT / "docs" / "index-estimates.json").read_text(encoding="utf-8"))
    assert estimates["models"], "no estimates to test with"
    copies = scoring.inherit_unmeasured(bench, catalog)
    both = scoring.with_estimates(copies, catalog, estimates["models"])
    assert {k for k, v in both.items() if scoring._estimated(v)} == set(estimates["models"]) & {
        m["id"] for m in catalog["models"]
    }
    plain = scoring.with_composites(bench)
    with_both = scoring.with_composites(both)
    assert {k: with_both[k] for k in plain} == plain
    for task in (scoring.Task("coding", "high"), PLANNING, scoring.Task("agentic", "high")):
        key = scoring.CATEGORY_EVIDENCE[task.category]
        assert scoring._evidence_scale(catalog, with_both, key) == scoring._evidence_scale(
            catalog, plain, key
        )
        assert scoring.market_exchange_rate(catalog, both, task) == pytest.approx(
            scoring.market_exchange_rate(catalog, bench, task)
        )
    for model_id in sorted(set(bench))[:5]:
        assert scoring.estimated_aa_index(both, model_id, "low") == (
            scoring.estimated_aa_index(bench, model_id, "low")
        )


def test_a_wider_band_ranks_the_estimate_further_below_it() -> None:
    # From later launches' tables (band 5): ranked 2.5 below, printed as is.
    assert scoring.estimate_penalty(5.0) == 2.5 and scoring.estimate_penalty(3.5) == P
    assert scoring.estimate_penalty(None) == P
    out = _rows({"gemini-9-nova": {"index": 60.0, "band": 5.0}})
    assert out["gemini-9-nova"]["evaluations"] == {INDEX: 57.5}
    assert out["gemini-9-nova"]["estimated"]["penalty"] == 2.5
    assert scoring.ladder_aa(out, "gemini-9-nova", "max") == (60.0, True)
    lad = scoring.ladder(PLANNING, CONTEXT, catalog=WITH_NOVA, benchmarks=out)
    assert lad is not None
    nova = next(p for p in lad.frontier if p.candidate.model_id == "gemini-9-nova")
    assert nova.candidate.aa_estimate_penalty == 2.5 and nova.aa_index == 57.5
    assert scoring.aa_text(nova) == "≈60"
