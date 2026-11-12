"""A new version AA has not measured stands where its previous version did.

The operator's rule (2026-11-12): until Artificial Analysis measures Fable 5.2,
it takes Fable 5.1's row, shown ≈, as it already takes Fable 5.1's rating
letters. Without it the series left the frontier: rank drops Fable 5.1
wherever Fable 5.2 runs, and an unmeasured model has no frontier point. A new
series has no previous version and stays unmeasured. The copies are figures
for their own model only, so every statistic read over the measured models
(composites, evidence scales, the market line, effort shifts) is unchanged.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_successor import BENCH, CATALOG, CONTEXT, TASK, _model

from roadmodel import scoring

ROOT = Path(__file__).resolve().parents[1]

# GPT-6.1 Sol and Gemini 9 Nova (a new series) are unmeasured.
UNMEASURED = {k: v for k, v in BENCH.items() if k != "gpt-6.1-sol"}
WITH_NOVA = copy.deepcopy(CATALOG)
WITH_NOVA["models"].append(_model("gemini-9-nova", "Gemini 9 Nova", 1.0, 5.0, "google"))


def test_an_unmeasured_version_copies_its_newest_previous_version() -> None:
    bench = {**UNMEASURED, "gpt-5-sol": BENCH["gpt-6-sol"] | {"aa_effort": "high"}}
    out = scoring.inherit_unmeasured(bench, WITH_NOVA)
    assert out["gpt-6.1-sol"] == {**BENCH["gpt-6-sol"], "inherited_from": "gpt-6-sol"}
    assert "gemini-9-nova" not in out  # a new series has no previous version
    assert out["opus"] == BENCH["opus"]  # a measured model keeps its own row
    assert "gpt-6.1-sol" not in bench  # the input is left as it was


def test_a_measured_version_keeps_its_own_row() -> None:
    assert scoring.inherit_unmeasured(BENCH, CATALOG) == BENCH


def test_the_loaded_rows_put_the_new_version_on_the_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scoring, "_load_benchmarks", lambda: UNMEASURED)
    ranking = scoring.rank(TASK, CONTEXT, catalog=CATALOG)
    sol = next(c for c in ranking.candidates if c.model_id == "gpt-6.1-sol")
    assert sol.aa_inherited_from == "gpt-6-sol"
    assert "gpt-6-sol" not in {c.model_id for c in ranking.candidates}
    lad = scoring.ladder(TASK, CONTEXT, catalog=CATALOG)
    assert lad is not None
    assert "gpt-6.1-sol" in {p.candidate.model_id for p in lad.frontier}
    # The engine's ladder table marks the copied figure as an estimate.
    table = scoring.render_ladder_table({"knowledge/medium": lad})
    assert "GPT-6.1 Sol (AA ≈" in table


def test_without_the_copy_the_series_had_no_frontier_point() -> None:
    lad = scoring.ladder(TASK, CONTEXT, catalog=CATALOG, benchmarks=UNMEASURED)
    assert lad is not None
    assert not {"gpt-6-sol", "gpt-6.1-sol"} & {p.candidate.model_id for p in lad.frontier}


def test_a_copied_figure_reads_as_an_estimate() -> None:
    bench = scoring.inherit_unmeasured(UNMEASURED, CATALOG)
    assert scoring.ladder_aa(bench, "gpt-6.1-sol", "max") == (47.6, True)
    assert scoring.ladder_aa(bench, "gpt-6.1-sol", "medium") == (39.8, True)
    assert scoring.ladder_aa(bench, "gpt-6-sol", "max") == (47.6, False)


def test_the_copies_change_no_statistic_over_the_measured_models() -> None:
    catalog = json.loads((ROOT / "docs" / "catalog.json").read_text(encoding="utf-8"))
    bench = json.loads((ROOT / "docs" / "benchmarks.json").read_text(encoding="utf-8"))["models"]
    # Two of the catalog's newest versions, unmeasured: their rows are dropped.
    measured = {m["id"] for m in catalog["models"] if m["id"] in bench}
    newest = [
        mid
        for mid in sorted(measured)
        if any(scoring._series.is_newer(o, mid) for o in measured)
        and not any(scoring._series.is_newer(mid, o) for o in measured)
    ][:2]
    assert newest, "the catalog has no measured later version to test with"
    base = {k: v for k, v in bench.items() if k not in newest}
    inherited = scoring.inherit_unmeasured(base, catalog)
    assert set(newest) <= {k for k, v in inherited.items() if scoring._inherited_from(v)}

    plain, with_copies = scoring.with_composites(base), scoring.with_composites(inherited)
    assert {k: with_copies[k] for k in plain} == plain
    for mid in newest:
        source = inherited[mid]["inherited_from"]
        assert with_copies[mid]["evaluations"] == plain[source]["evaluations"]
    for task in (scoring.Task("coding", "high"), scoring.Task("planning", "medium")):
        key = scoring.CATEGORY_EVIDENCE[task.category]
        assert scoring._evidence_scale(catalog, with_copies, key) == scoring._evidence_scale(
            catalog, plain, key
        )
        assert scoring.market_exchange_rate(catalog, inherited, task) == pytest.approx(
            scoring.market_exchange_rate(catalog, base, task)
        )
    for model_id in sorted(measured - set(newest))[:5]:
        assert scoring.estimated_aa_index(inherited, model_id, "low") == (
            scoring.estimated_aa_index(base, model_id, "low")
        )
