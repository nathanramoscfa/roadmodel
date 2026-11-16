"""A day-one AA Index estimate for unmeasured models (roadmodel.estimate).

Until Artificial Analysis measures a new model, its launch table places it: the
measured models the vendor compares it with are anchors on the index's scale.
The /models page shows the estimate ≈ with its band; picks don't read it yet.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from roadmodel import estimate

REPO = Path(__file__).resolve().parent.parent
INDEX = estimate.INDEX_KEY


def _bench(**rows: tuple[float, str, dict[str, float] | None]) -> dict[str, Any]:
    """{id: (index, release_date, components)} → a benchmarks.json models map."""
    out: dict[str, Any] = {}
    for mid, (index, date, comps) in rows.items():
        out[mid.replace("_", "-")] = {
            "release_date": date,
            "evaluations": {INDEX: index, **(comps or {})},
        }
    return out


BENCH = _bench(
    old_a=(40.0, "2026-01-01", None),
    old_b=(50.0, "2026-02-01", None),
    old_c=(60.0, "2026-03-01", None),
    late=(90.0, "2026-12-01", None),
)


def _entry(
    rows: list[list[float | None]], columns: list[str | None], **extra: Any
) -> dict[str, Any]:
    return {
        "release_date": "2026-06-01",
        "tables": [
            {
                "columns": columns,
                "rows": [{"benchmark": f"B{i}", "values": r, **extra} for i, r in enumerate(rows)],
            }
        ],
    }


COLS: list[str | None] = ["new", "old-a", "old-b", "old-c"]


def test_three_anchors_place_the_model_on_their_least_squares_line() -> None:
    # Scores 40/50/60 map one-to-one onto the index; the new model scores 55.
    entry = _entry([[55, 40, 50, 60]] * 3, COLS)
    # One row repeated is one row: identical (benchmark, score) rows are dropped.
    entry["tables"][0]["rows"] = [
        {"benchmark": f"B{i}", "values": [55 + i, 40 + i, 50 + i, 60 + i]} for i in range(3)
    ]
    est = estimate.estimate("new", entry, BENCH)
    assert est is not None
    assert est.index == pytest.approx(55 - estimate.OPTIMISM, abs=0.05)
    assert est.anchors == ("old-a", "old-b", "old-c")
    assert est.rows == 3 and est.band == estimate.BAND and est.method == "anchors"


def test_two_anchors_use_the_line_through_their_spread() -> None:
    assert estimate.row_estimate(
        45.0, {"old-a": 40.0, "old-b": 50.0}, {"old-a": 40.0, "old-b": 50.0}
    ) == pytest.approx(45.0)
    # Far outside the anchors, the line stops three spreads from their middle.
    assert estimate.row_estimate(
        1000.0, {"old-a": 40.0, "old-b": 50.0}, {"old-a": 40.0, "old-b": 50.0}
    ) == pytest.approx(60.0)
    # Anchors that tie on the row say nothing about it.
    assert (
        estimate.row_estimate(45.0, {"old-a": 40.0, "old-b": 40.0}, {"old-a": 40.0, "old-b": 50.0})
        is None
    )


def test_only_models_released_before_it_are_anchors() -> None:
    # On launch day a later model was not measured; its column is ignored, so
    # these rows have two anchors (old-a, old-b), not three.
    cols: list[str | None] = ["new", "old-a", "old-b", "late"]
    rows = estimate.anchor_rows("new", _entry([[45, 40, 50, 99]], cols), BENCH)
    assert rows == [(45.0, {"old-a": 40.0, "old-b": 50.0})]


def test_rows_off_the_percent_scale_and_unlisted_columns_are_skipped() -> None:
    cols: list[str | None] = ["new", "old-a", "old-b", None]
    entry = _entry([[1500, 1400, 1450, 1300], [45, 40, 50, 70]], cols)
    assert estimate.anchor_rows("new", entry, BENCH) == [(45.0, {"old-a": 40.0, "old-b": 50.0})]


def test_a_lower_is_better_row_is_flipped() -> None:
    entry = _entry([[10, 30, 20]], ["new", "old-a", "old-b"], higher_is_better=False)
    assert estimate.anchor_rows("new", entry, BENCH) == [(-10.0, {"old-a": -30.0, "old-b": -20.0})]


def test_too_thin_a_table_gives_no_estimate() -> None:
    # One anchor per row: nothing to place the model between.
    one = _entry([[45 + i, 40 + i] for i in range(5)], ["new", "old-a"])
    assert estimate.estimate("new", one, BENCH) is None
    # Two anchors but fewer rows than the floor.
    short = _entry([[45, 40, 50], [46, 41, 51]], ["new", "old-a", "old-b"])
    assert estimate.estimate("new", short, BENCH) is None


def test_measured_models_are_never_estimated() -> None:
    entry = _entry(
        [[55 + i, 40 + i, 50 + i, 60 + i] for i in range(3)], ["old-b", "old-a", "new", "old-c"]
    )
    estimates = estimate.estimate_all({"old-b": entry}, BENCH)
    assert "old-b" not in estimates
    # The unmeasured model its table lists is placed from it (the fallback).
    assert estimates["new"].via == ("old-b",)


def test_reported_index_components_add_the_component_fit() -> None:
    # A snapshot where the index is exactly 100 × HLE: the fit recovers it.
    rows = {
        f"m{i}": (100 * h, f"2026-0{1 + i % 9}-01", {"hle": h})
        for i, h in enumerate([0.1, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.62, 0.15])
    }
    bench = _bench(**rows)
    entry = {
        "release_date": "2026-06-01",
        "tables": [
            {
                "columns": ["new"],
                "rows": [
                    {
                        "benchmark": "Humanity's Last Exam (no tools)",
                        "values": [48.0],
                        "component": "hle",
                    }
                ],
            }
        ],
    }
    est = estimate.estimate("new", entry, bench)
    assert est is not None and est.method == "components"
    assert est.index == pytest.approx(48.0, abs=1.5)
    assert estimate.components_reported("new", entry) == {"hle": 0.48}


def test_the_committed_estimates_were_built_from_the_committed_launch_tables() -> None:
    """Edit update/launch-tables.json, then rerun update/build_index_estimates.py."""
    doc = json.loads((REPO / "docs" / "index-estimates.json").read_text())
    tables = (REPO / "update" / "launch-tables.json").read_bytes()
    assert doc["launch_tables_sha256"] == hashlib.sha256(tables).hexdigest()


def test_every_launch_table_is_well_formed() -> None:
    doc = json.loads((REPO / "update" / "launch-tables.json").read_text())
    assert doc["schema_version"] == 1
    for mid, entry in doc["models"].items():
        assert isinstance(entry["release_date"], str) and len(entry["release_date"]) == 10, mid
        for table in entry["tables"]:
            cols = table["columns"]
            assert mid in cols, f"{mid}: its launch table has no column for it"
            assert all(c is None or isinstance(c, str) for c in cols), mid
            assert table["source"].startswith("https://"), mid
            for row in table["rows"]:
                assert len(row["values"]) == len(cols), (mid, row["benchmark"])
                nums = [v for v in row["values"] if v is not None]
                assert all(0 <= v <= 100 for v in nums), (mid, row["benchmark"])
                assert row.get("component") in (None, *estimate.COMPONENTS), (mid, row["benchmark"])


# --------------------------------------------------------------------------- #
# The fallback: later launch tables that list a model its own table can't place.


def _launch(owner: str, released: str, columns: list[str | None], rows: list[list[float]]) -> Any:
    return {
        "release_date": released,
        "tables": [
            {
                "source": "https://vendor.example/launch",
                "columns": columns,
                "rows": [{"benchmark": f"B{i}", "values": r} for i, r in enumerate(rows)],
            }
        ],
    }


# "thin" sets itself beside one measured model; "later" (released after it)
# lists it beside three, where scores 40/50/60 map one-to-one onto the index.
THIN = _launch("thin", "2026-06-01", ["thin", "old-a", None], [[55, 40, 70]] * 3)
LATER = _launch(
    "later",
    "2026-09-01",
    ["later", "thin", "old-a", "old-b", "old-c"],
    [[80 + i, 55 + i, 40 + i, 50 + i, 60 + i] for i in range(3)],
)


def test_later_launch_tables_place_a_model_its_own_table_cannot() -> None:
    tables = {"thin": THIN, "later": LATER}
    assert estimate.estimate("thin", THIN, BENCH) is None
    est = estimate.estimate_all(tables, BENCH)["thin"]
    assert est.method == estimate.OTHER_METHOD and est.band == estimate.OTHER_BAND
    assert est.index == pytest.approx(55 - estimate.OTHER_OPTIMISM, abs=0.05)
    assert est.anchors == ("old-a", "old-b", "old-c") and est.rows == 3
    assert est.via == ("later",)
    assert est.as_json()["via"] == ["later"]
    # A model with no launch table of its own is placed the same way.
    assert estimate.estimate_all({"later": LATER}, BENCH)["thin"].via == ("later",)


def test_the_listing_tables_own_model_and_later_models_never_anchor() -> None:
    # Even once "later" is measured, its own column stays out (its vendor's own
    # figures), as does any model released after it ("late", 2026-12-01).
    bench = {**BENCH, "later": {"release_date": "2026-09-01", "evaluations": {INDEX: 99.0}}}
    table = LATER["tables"][0]
    cols = [*table["columns"], "late"]
    rows = [{**r, "values": [*r["values"], 95.0]} for r in table["rows"]]
    later = {**LATER, "tables": [{**table, "columns": cols, "rows": rows}]}
    rows_used = estimate.other_rows("thin", {"thin": THIN, "later": later}, bench)
    assert {a for _, anchors, _ in rows_used for a in anchors} == {"old-a", "old-b", "old-c"}
    assert {owner for *_, owner in rows_used} == {"later"}


def test_a_model_its_own_table_places_ignores_other_tables() -> None:
    own = _launch(
        "thin",
        "2026-06-01",
        ["thin", "old-a", "old-b"],
        [[45 + i, 40 + i, 50 + i] for i in range(3)],
    )
    est = estimate.estimate_all({"thin": own, "later": LATER}, BENCH)["thin"]
    assert est.method == "anchors" and est.via == () and "via" not in est.as_json()


def test_too_few_rows_from_other_tables_give_no_estimate() -> None:
    later = {**LATER, "tables": [{**LATER["tables"][0], "rows": LATER["tables"][0]["rows"][:2]}]}
    assert "thin" not in estimate.estimate_all({"thin": THIN, "later": later}, BENCH)


# --------------------------------------------------------------------------- #
# Letter figures, and the typed check on the estimates file.

import sys  # noqa: E402

sys.path.insert(0, str(REPO / "update"))
import launch_data  # noqa: E402

FIGURE_BENCH = {
    mid: {
        "release_date": date,
        "evaluations": {INDEX: index, "hle": hle, "terminalbench_v4_0": tb4},
    }
    for mid, date, index, hle, tb4 in (
        ("old-a", "2026-01-01", 40.0, 0.30, 0.20),
        ("old-b", "2026-02-01", 50.0, 0.40, 0.40),
        ("old-c", "2026-03-01", 60.0, 0.50, 0.60),
    )
}


def test_letter_figures_come_from_the_rows_as_the_index_does() -> None:
    # Scores 40/50/60 put HLE at 30/40/50 and Terminal-Bench 4.0 at 20/40/60;
    # the new model scores 55 on each row.
    rows = [[55 + i, 40 + i, 50 + i, 60 + i] for i in range(3)]
    entry = _entry(rows, COLS)
    est = estimate.estimate("new", entry, FIGURE_BENCH)
    assert est is not None
    assert est.figures["hle"] == pytest.approx((45 - estimate.FIGURE_OPTIMISM["hle"]) / 100)
    opt = estimate.FIGURE_OPTIMISM["terminalbench_v4_0"]
    assert est.figures["terminalbench_v4_0"] == pytest.approx((50 - opt) / 100)
    # No anchor has AA-LCR or SciCode measured: those figures are left out.
    assert set(est.figures) == {"hle", "terminalbench_v4_0"}
    assert est.as_json()["figures"] == dict(sorted(est.figures.items()))
    # The index is unchanged by them.
    assert est.index == pytest.approx(55 - estimate.OPTIMISM, abs=0.05)


def test_every_table_of_a_launch_keeps_its_anchors() -> None:
    # Two tables: the second's anchors count as fully as the first's.
    first = _entry([[45 + i, 40 + i, 50 + i] for i in range(2)], ["new", "old-a", "old-b"])
    second = _entry([[55 + i, 50 + i, 60 + i] for i in range(2)], ["new", "old-b", "old-c"])
    for i, row in enumerate(second["tables"][0]["rows"]):
        row["benchmark"] = f"C{i}"
    entry = {**first, "tables": first["tables"] + second["tables"]}
    assert len(estimate.anchor_rows("new", entry, BENCH)) == 4
    assert len(estimate.anchor_rows("new", entry, FIGURE_BENCH, "hle")) == 4


def test_the_committed_estimates_pass_the_typed_check() -> None:
    doc = json.loads((REPO / "docs" / "index-estimates.json").read_text())
    catalog = {m["id"] for m in json.loads((REPO / "docs" / "catalog.json").read_text())["models"]}
    bench = json.loads((REPO / "docs" / "benchmarks.json").read_text())["models"]
    launch_data.check_index_estimates(doc, catalog | set(bench), catalog)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda e: e.__setitem__("index", 140), "index_estimates_value"),
        (lambda e: e.__setitem__("band", 0), "index_estimates_value"),
        (lambda e: e.__setitem__("method", "vibes"), "index_estimates_entry"),
        (lambda e: e.__setitem__("anchors", ["<b>x</b>"]), "index_estimates_identity"),
        (lambda e: e.__setitem__("via", ["made-up-id"]), "index_estimates_identity"),
        (lambda e: e.__setitem__("effort", "Max effort!"), "index_estimates_entry"),
        (lambda e: e.__setitem__("figures", {"hle": 2}), "index_estimates_value"),
        (lambda e: e.__setitem__("figures", {"mmlu": 0.5}), "index_estimates_entry"),
        (lambda e: e.__setitem__("note", "extra"), "index_estimates_entry"),
    ],
)
def test_the_estimates_check_refuses_anything_but_typed_data(change: Any, error: str) -> None:
    entry = {"index": 50.0, "band": 4.0, "method": "anchors", "anchors": ["old-a"], "rows": 3}
    change(entry)
    doc = {
        "schema_version": 1,
        "about": "x",
        "launch_tables_sha256": "0" * 64,
        "models": {"new": entry},
    }
    with pytest.raises(ValueError, match=error):
        launch_data.check_index_estimates(doc, {"old-a", "new"}, {"new"})


# --------------------------------------------------------------------------
# Each maker's launch tables take their own optimism (MAKER_OPTIMISM).
# --------------------------------------------------------------------------


def _figure_rows(model_id: str) -> dict[str, Any]:
    rows = [[55 + i, 40 + i, 50 + i, 60 + i] for i in range(3)]
    return _entry(rows, [model_id, "old-a", "old-b", "old-c"])


def test_a_makers_record_corrects_its_index_and_figures() -> None:
    # The same table under an OpenAI id and an id no rule names: the index and
    # HLE take OpenAI's own correction, Terminal-Bench 4.0 the all-maker one.
    openai = estimate.estimate("gpt-9-nova", _figure_rows("gpt-9-nova"), FIGURE_BENCH)
    nobody = estimate.estimate("new", _figure_rows("new"), FIGURE_BENCH)
    assert openai is not None and nobody is not None
    by_maker = estimate.MAKER_OPTIMISM
    assert openai.index == pytest.approx(55 - by_maker[INDEX]["openai"], abs=0.05)
    assert nobody.index == pytest.approx(55 - estimate.OPTIMISM, abs=0.05)
    assert openai.figures["hle"] == pytest.approx((45 - by_maker["hle"]["openai"]) / 100)
    assert nobody.figures["hle"] == pytest.approx((45 - estimate.FIGURE_OPTIMISM["hle"]) / 100)
    tb4 = estimate.FIGURE_OPTIMISM["terminalbench_v4_0"]
    assert openai.figures["terminalbench_v4_0"] == pytest.approx((50 - tb4) / 100)
    assert openai.band == nobody.band == estimate.BAND


def test_optimism_falls_back_to_the_all_maker_figure() -> None:
    # A maker with no measured launch table behind it (Mistral, Cursor) and a
    # figure that does not differ by maker (SciCode, Terminal-Bench 4.0).
    assert estimate.optimism(INDEX, "codestral") == estimate.OPTIMISM
    assert estimate.optimism(INDEX, "composer-2.5") == estimate.OPTIMISM
    assert estimate.optimism(INDEX, "unknown-model") == estimate.OPTIMISM
    for key in ("scicode", "terminalbench_v4_0"):
        assert estimate.optimism(key, "gemini-4-carbon") == estimate.FIGURE_OPTIMISM[key]
    assert estimate.optimism(INDEX, "gemini-4-carbon") == estimate.MAKER_OPTIMISM[INDEX]["google"]
    assert estimate.optimism("lcr", "kimi-k4") == estimate.MAKER_OPTIMISM["lcr"]["moonshot"]


def test_maker_corrections_cover_known_figures_and_lean_toward_the_pool() -> None:
    # Only the index and letter figures are corrected, every maker named is
    # one maker() can return, and partial pooling keeps each maker's figure
    # nearer the all-maker one than any single launch was (within 8 points).
    makers = {name for _, name in estimate._MAKER_RULES}
    assert set(estimate.MAKER_OPTIMISM) <= {INDEX, *estimate.FIGURE_OPTIMISM}
    for key, by_maker in estimate.MAKER_OPTIMISM.items():
        pooled = estimate.OPTIMISM if key == INDEX else estimate.FIGURE_OPTIMISM[key]
        assert set(by_maker) <= makers
        assert all(abs(v - pooled) < 8 for v in by_maker.values())


def test_maker_matches_the_selector_prose_rules() -> None:
    # update/stale_claims.py maker_of names makers in the selector's prose; the
    # estimator must agree with it on every model it could estimate.
    import sys

    sys.path.insert(0, str(REPO / "update"))
    import stale_claims

    catalog = json.loads((REPO / "docs" / "catalog.json").read_text())["models"]
    tables = json.loads((REPO / "update" / "launch-tables.json").read_text())["models"]
    ids = {m["id"] for m in catalog} | set(tables)
    ids |= {"gpt-oss-120b", "sonnet-4.6", "kimi-k3", "muse-wonder", "glm-5.3", "grok-4.7"}
    for mid in sorted(ids):
        assert estimate.maker(mid) == stale_claims.maker_of(mid), mid
    rules = [(rx.pattern, name) for rx, name in estimate._MAKER_RULES]
    assert rules == [(rx.pattern, name) for rx, name in stale_claims._MAKER_RULES]
