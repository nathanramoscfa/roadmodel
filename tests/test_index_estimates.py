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
    assert estimate.estimate_all({"old-b": entry}, BENCH) == {}


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
