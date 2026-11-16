"""A day-one estimate of an unmeasured model's AA Intelligence Index.

Artificial Analysis measures a new model days or weeks after it launches. Until
it does, roadmodel estimates the index from the model's own launch table: the
vendor sets the new model beside older ones on the same benchmarks, run the
same way, and the older columns Artificial Analysis has measured place the new
model on the index's scale. Two methods, averaged when both apply:

* Launch-table anchors. Each benchmark row with two or more anchors (measured
  models released before this one) maps that row's scores onto the index: a
  least-squares line across three or more anchors, the line through their
  spread otherwise. The median over the rows, less the launch-table optimism
  (vendors lead with the benchmarks their new model wins), is the estimate.
* Index components. When the launch table reports Humanity's Last Exam without
  tools or Terminal-Bench 4.0, two of the index's own components, a fit of the
  index on Artificial Analysis's measurements of those components and the
  release date places the model.

Calibrated by leave-one-out over the launch tables of the 27 models Artificial
Analysis has measured whose tables carry two or more anchors (2026-11): a
typical miss of 2.6 index points, a root-mean-square miss of 3.8, and 23 of the
27 within 5 points. ``BAND`` is that error, rounded.

When a model's own table names too few measured models to place it (Gemini 4
Hydrogen's sets it beside one), later launch tables that list it as a
competitor can (``from_other_tables``): their other measured columns anchor it
the same way. Leave-one-out over the 17 measured models later tables list
(2026-11): a typical miss of 3.9 points, root-mean-square 4.5; on the 8 whose
own table could not place them, 4.3 and 5.1, 5 of the 8 within 5 points. So it
stands in only where the model's own table cannot, with the wider
``OTHER_BAND``.

The inputs live in update/launch-tables.json; update/build_index_estimates.py
writes the estimates to docs/index-estimates.json, which the /models page shows
and the scorer ranks on (scoring.with_estimates, less half the estimate's band).
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

INDEX_KEY: Final = "artificial_analysis_intelligence_index"

# Mean amount a launch table's anchor estimate overshoots Artificial Analysis's
# later measurement: vendors choose the benchmarks they lead with.
OPTIMISM: Final = 1.5
# Leave-one-out error of the combined estimate (RMSE, index points).
BAND: Final = 4.0
# An estimate needs this many distinct anchors and benchmark rows.
MIN_ANCHORS: Final = 2
MIN_ROWS: Final = 3
# The fallback from other models' launch tables (from_other_tables): their mean
# overshoot of the later measurement, and their leave-one-out error (RMSE 5.1 on
# the models their own table could not place, rounded down to the half point).
# A competitor's table flatters its own model, not the one it lists, so the
# overshoot is smaller than OPTIMISM.
OTHER_OPTIMISM: Final = 1.0
OTHER_BAND: Final = 5.0
OTHER_METHOD: Final = "other-tables"
# The four figures besides the index that update/derive_ratings.py letters a
# model on (benchmarks.json keys), each with its launch-table optimism in
# percentage points: the mean overshoot of the later measurement, leave-one-out
# over the measured models' launch tables (2026-11; 26 tables, 22 for SciCode and
# Terminal-Bench 4.0). Typical misses after it: HLE 3.9, AA-LCR 2.2, SciCode 3.3,
# Terminal-Bench 4.0 7.8 points. Lettered with the derivation's own rules, the
# estimates give the exact letter 94 times in 122 and an S to 22 of the 29 true
# S models. Means and trimmed means of the rows tied the median on all four but
# Terminal-Bench 4.0, where the median is clearly best (7.8 against 9.0).
FIGURE_OPTIMISM: Final = {"hle": 3.6, "lcr": 0.9, "scicode": 2.4, "terminalbench_v4_0": 4.2}
# The index components a launch table can report, by their benchmarks.json key.
COMPONENTS: Final = ("hle", "terminalbench_v4_0")
# Ridge strength for the component fit, on standardized inputs.
_RIDGE: Final = 0.1


@dataclass(frozen=True)
class Estimate:
    """An estimated index, its error band, and what it rests on."""

    index: float
    band: float
    method: str
    anchors: tuple[str, ...]
    rows: int
    # The models whose launch tables placed it, when not its own
    # (from_other_tables), earliest first.
    via: tuple[str, ...] = ()
    # Its estimated letter figures (FIGURE_OPTIMISM keys, as fractions like
    # benchmarks.json), from its own launch table only.
    figures: dict[str, float] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "index": self.index,
            "band": self.band,
            "method": self.method,
            "anchors": list(self.anchors),
            "rows": self.rows,
        }
        if self.via:
            out["via"] = list(self.via)
        if self.figures:
            out["figures"] = dict(sorted(self.figures.items()))
        return out


def measured_index(bench: Mapping[str, Any], model_id: str) -> float | None:
    """The AA Index Artificial Analysis measured for ``model_id``, or None."""
    return _measured(bench, model_id)


def _measured(bench: Mapping[str, Any], model_id: str) -> float | None:
    row = bench.get(model_id)
    if not isinstance(row, dict):
        return None
    value = (row.get("evaluations") or {}).get(INDEX_KEY)
    return float(value) if isinstance(value, (int, float)) else None


def _value(bench: Mapping[str, Any], model_id: str, key: str) -> float | None:
    """``key``'s measurement for ``model_id`` in points: the index as it is, a
    benchmarks.json fraction times 100."""
    row = bench.get(model_id)
    if not isinstance(row, dict):
        return None
    v = _number((row.get("evaluations") or {}).get(key))
    if v is None:
        return None
    return v if key == INDEX_KEY else v * 100


def _release(bench: Mapping[str, Any], model_id: str) -> str | None:
    row = bench.get(model_id)
    date = row.get("release_date") if isinstance(row, dict) else None
    return date if isinstance(date, str) and date else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def anchor_rows(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any], key: str = INDEX_KEY
) -> list[tuple[float, dict[str, float]]]:
    """Each usable row as (this model's score, {anchor: anchor's score}).

    An anchor is a column for a model with ``key`` measured (the index unless
    a letter figure is asked for), released before this one: on launch day it
    is the only kind Artificial Analysis had measured. Rows are percent scores;
    a lower-is-better row is negated so a higher score always means a stronger
    model.
    """
    released = str(entry.get("release_date") or "")
    out: list[tuple[float, dict[str, float]]] = []
    seen: set[tuple[str, float]] = set()
    for table in entry.get("tables") or []:
        columns = list(table.get("columns") or [])
        if model_id not in columns:
            continue
        own = columns.index(model_id)
        usable = {
            i: str(col)
            for i, col in enumerate(columns)
            if i != own
            and isinstance(col, str)
            and _value(bench, col, key) is not None
            and (date := _release(bench, col)) is not None
            and date < released
        }
        for row in table.get("rows") or []:
            values = list(row.get("values") or [])
            if len(values) != len(columns) or (score := _number(values[own])) is None:
                continue
            if any((v := _number(x)) is not None and not 0 <= v <= 100 for x in values):
                continue  # Elo, dollars and the like share no scale with percentages
            sign = 1.0 if row.get("higher_is_better", True) else -1.0
            anchors: dict[str, float] = {}
            for i, anchor in usable.items():
                if (v := _number(values[i])) is not None:
                    anchors[anchor] = max(anchors.get(anchor, -math.inf), sign * v)
            row_key = (re.sub(r"\W+", "", str(row.get("benchmark", "")).lower()), score)
            if len(anchors) >= 2 and row_key not in seen:
                seen.add(row_key)
                out.append((sign * score, anchors))
    return out


def row_estimate(
    score: float, anchors: Mapping[str, float], index: Mapping[str, float]
) -> float | None:
    """Where ``score`` falls on the index, judged by one row's anchors."""
    ids = sorted(anchors)
    xs = [anchors[a] for a in ids]
    ys = [index[a] for a in ids]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = statistics.pstdev(xs)
    if sx < 1e-9:
        return None
    if len(ids) >= 3:
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum(
            (x - mx) ** 2 for x in xs
        )
        if slope > 0:
            return my + slope * (score - mx)
    # Two anchors, or three that disagree on direction: the line through their
    # spread, kept within three spreads of their middle.
    z = max(-3.0, min(3.0, (score - mx) / sx))
    return my + z * statistics.pstdev(ys)


def from_anchors(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]
) -> tuple[float, tuple[str, ...], int] | None:
    """The anchor estimate, its anchors and its row count; None below the floor."""
    rows = anchor_rows(model_id, entry, bench)
    index = {a: v for _, anchors in rows for a in anchors if (v := _measured(bench, a)) is not None}
    estimates = [
        e for score, anchors in rows if (e := row_estimate(score, anchors, index)) is not None
    ]
    names = tuple(sorted({a for _, anchors in rows for a in anchors}))
    if len(estimates) < MIN_ROWS or len(names) < MIN_ANCHORS:
        return None
    return statistics.median(estimates) - OPTIMISM, names, len(estimates)


def figures(model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]) -> dict[str, float]:
    """Each letter figure (FIGURE_OPTIMISM) the launch table places, as a
    fraction: its rows mapped through the anchors' measurements of that figure,
    as the index is, less the figure's optimism. A figure below the floors is
    left out."""
    out: dict[str, float] = {}
    for key, optimism in FIGURE_OPTIMISM.items():
        rows = anchor_rows(model_id, entry, bench, key)
        values = {
            a: v for _, anchors in rows for a in anchors if (v := _value(bench, a, key)) is not None
        }
        placed = [
            e for score, anchors in rows if (e := row_estimate(score, anchors, values)) is not None
        ]
        names = {a for _, anchors in rows for a in anchors}
        if len(placed) < MIN_ROWS or len(names) < MIN_ANCHORS:
            continue
        out[key] = round(min(1.0, max(0.0, (statistics.median(placed) - optimism) / 100)), 4)
    return out


def _years(date: str) -> float:
    y, m, d = (int(part) for part in date.split("-"))
    return (y - 2025) + (m - 1) / 12 + (d - 1) / 365


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def components_reported(model_id: str, entry: Mapping[str, Any]) -> dict[str, float]:
    """The index components this launch table reports for the model, as fractions."""
    out: dict[str, float] = {}
    for table in entry.get("tables") or []:
        columns = list(table.get("columns") or [])
        if model_id not in columns:
            continue
        own = columns.index(model_id)
        for row in table.get("rows") or []:
            key = row.get("component")
            values = list(row.get("values") or [])
            if key in COMPONENTS and len(values) == len(columns):
                if (v := _number(values[own])) is not None:
                    out.setdefault(str(key), v / 100)
    return out


def from_components(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]
) -> float | None:
    """The component estimate: the index fitted on Artificial Analysis's own
    measurements of the reported components and the release date."""
    reported = components_reported(model_id, entry)
    released = entry.get("release_date")
    if not reported or not isinstance(released, str):
        return None
    features = [k for k in COMPONENTS if k in reported]
    train: list[tuple[list[float], float]] = []
    for mid in bench:
        target = _measured(bench, mid)
        date = _release(bench, mid)
        evals = (bench[mid] or {}).get("evaluations") or {}
        xs = [_number(evals.get(k)) for k in features]
        if target is None or date is None or any(x is None for x in xs):
            continue
        train.append(([x for x in xs if x is not None] + [_years(date)], target))
    point = [reported[k] for k in features] + [_years(released)]
    k = len(point)
    if len(train) < 3 * k + 3:
        return None
    n = len(train)
    mu = [statistics.fmean(x[j] for x, _ in train) for j in range(k)]
    sd = [statistics.pstdev([x[j] for x, _ in train]) or 1.0 for j in range(k)]
    z = [[(x[j] - mu[j]) / sd[j] for j in range(k)] for x, _ in train]
    ybar = statistics.fmean(y for _, y in train)
    yc = [y - ybar for _, y in train]
    gram = [
        [sum(r[p] * r[q] for r in z) + (_RIDGE * n if p == q else 0.0) for q in range(k)]
        for p in range(k)
    ]
    beta = _solve(gram, [sum(r[p] * y for r, y in zip(z, yc, strict=True)) for p in range(k)])
    return ybar + sum(b * (point[j] - mu[j]) / sd[j] for j, b in enumerate(beta))


def estimate(model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]) -> Estimate | None:
    """The model's estimated index, or None when its launch table is too thin."""
    anchored = from_anchors(model_id, entry, bench)
    component = from_components(model_id, entry, bench)
    parts = [p for p in (anchored[0] if anchored else None, component) if p is not None]
    if not parts:
        return None
    method = "+".join(
        name
        for name, part in (("anchors", anchored), ("components", component))
        if part is not None
    )
    return Estimate(
        index=round(statistics.fmean(parts), 1),
        band=BAND,
        method=method,
        anchors=anchored[1] if anchored else (),
        rows=anchored[2] if anchored else 0,
        figures=figures(model_id, entry, bench),
    )


def other_rows(
    model_id: str, tables: Mapping[str, Any], bench: Mapping[str, Any]
) -> list[tuple[float, dict[str, float], str]]:
    """Each usable row of another model's launch table that lists ``model_id``,
    as (its score, {anchor: anchor's score}, the table's own model).

    An anchor is a measured column released before the table's own model. That
    model never anchors, nor one launched with it: its column is its vendor's
    own figures, and anchoring on it widened the backtest's misses (RMSE 4.9
    against 4.5). Where the table lists ``model_id`` at several settings, its
    best stands for it, as Artificial Analysis runs a model at its top effort.
    """
    out: list[tuple[float, dict[str, float], str]] = []
    seen: set[tuple[str, float]] = set()
    owners = sorted(
        (o for o in tables if o != model_id and isinstance(tables[o], Mapping)),
        key=lambda o: (str(tables[o].get("release_date") or ""), o),
    )
    for owner in owners:
        released = str(tables[owner].get("release_date") or "")
        for table in tables[owner].get("tables") or []:
            columns = list(table.get("columns") or [])
            mine = [i for i, col in enumerate(columns) if col == model_id]
            if not mine:
                continue
            usable = {
                i: str(col)
                for i, col in enumerate(columns)
                if isinstance(col, str)
                and col not in (model_id, owner)
                and _measured(bench, col) is not None
                and (date := _release(bench, col)) is not None
                and date < released
            }
            for row in table.get("rows") or []:
                values = list(row.get("values") or [])
                if len(values) != len(columns):
                    continue
                if any((v := _number(x)) is not None and not 0 <= v <= 100 for x in values):
                    continue
                sign = 1.0 if row.get("higher_is_better", True) else -1.0
                own = [sign * v for i in mine if (v := _number(values[i])) is not None]
                if not own:
                    continue
                anchors: dict[str, float] = {}
                for i, anchor in usable.items():
                    if (v := _number(values[i])) is not None:
                        anchors[anchor] = max(anchors.get(anchor, -math.inf), sign * v)
                key = (re.sub(r"\W+", "", str(row.get("benchmark", "")).lower()), max(own))
                if len(anchors) >= 2 and key not in seen:
                    seen.add(key)
                    out.append((max(own), anchors, owner))
    return out


def from_other_tables(
    model_id: str, tables: Mapping[str, Any], bench: Mapping[str, Any]
) -> Estimate | None:
    """The estimate from other models' launch tables that list ``model_id``
    (:func:`other_rows`), by the anchor method and its floors; None below them."""
    rows = other_rows(model_id, tables, bench)
    index = {
        a: v for _, anchors, _ in rows for a in anchors if (v := _measured(bench, a)) is not None
    }
    placed = [
        (e, owner)
        for score, anchors, owner in rows
        if (e := row_estimate(score, anchors, index)) is not None
    ]
    names = tuple(sorted({a for _, anchors, _ in rows for a in anchors}))
    if len(placed) < MIN_ROWS or len(names) < MIN_ANCHORS:
        return None
    via: list[str] = []
    for _, owner in placed:
        if owner not in via:
            via.append(owner)
    return Estimate(
        index=round(statistics.median(e for e, _ in placed) - OTHER_OPTIMISM, 1),
        band=OTHER_BAND,
        method=OTHER_METHOD,
        anchors=names,
        rows=len(placed),
        via=tuple(via),
    )


def estimate_all(tables: Mapping[str, Any], bench: Mapping[str, Any]) -> dict[str, Estimate]:
    """An estimate for every model Artificial Analysis has not measured that a
    launch table names: from its own table, else from the others that list it
    (:func:`from_other_tables`)."""
    named = set(tables)
    for entry in tables.values():
        for table in (entry.get("tables") or []) if isinstance(entry, Mapping) else []:
            named |= {c for c in table.get("columns") or [] if isinstance(c, str)}
    out: dict[str, Estimate] = {}
    for model_id in sorted(named):
        if _measured(bench, model_id) is not None:
            continue
        entry = tables.get(model_id)
        est = estimate(model_id, entry, bench) if isinstance(entry, Mapping) else None
        if est is None:
            est = from_other_tables(model_id, tables, bench)
        if est is not None:
            out[model_id] = est
    return out
