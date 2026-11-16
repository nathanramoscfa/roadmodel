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

import datetime
import math
import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
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


def _release(bench: Mapping[str, Any], model_id: str) -> str | None:
    row = bench.get(model_id)
    date = row.get("release_date") if isinstance(row, dict) else None
    return date if isinstance(date, str) and date else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def anchor_rows(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]
) -> list[tuple[float, dict[str, float]]]:
    """Each usable row as (this model's score, {anchor: anchor's score}).

    An anchor is a column for a model with a measured index, released before
    this one: on launch day it is the only kind Artificial Analysis had
    measured. Rows are percent scores; a lower-is-better row is negated so a
    higher score always means a stronger model.
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
            and _measured(bench, col) is not None
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
            key = (re.sub(r"\W+", "", str(row.get("benchmark", "")).lower()), score)
            if len(anchors) >= 2 and key not in seen:
                seen.add(key)
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


_ID = re.compile(r"[a-z0-9][a-z0-9.\-]{0,63}")
_TEXT = re.compile(r"[^\x00-\x1f<>\"`\\]{1,120}")
_URL = re.compile(r"https://[A-Za-z0-9.\-]+(?:/[^\s<>\"`\\]*)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ENTRY_KEYS = frozenset({"release_date", "tables", "checked_on", "attempts"})
_TABLE_KEYS = frozenset({"source", "columns", "rows"})
_ROW_KEYS = frozenset({"benchmark", "values", "higher_is_better", "component"})


def _date(value: Any, what: str) -> None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError(f"launch_tables_{what}")
    datetime.date.fromisoformat(value)


def check_launch_tables(doc: Any, roster: set[str], catalog_ids: set[str]) -> None:
    """Raise ValueError unless ``doc`` is a well-formed update/launch-tables.json:
    one entry per catalog model, each table's columns ids from ``roster`` (or
    null) with the model's own among them, every value a percentage or null, and
    no free text beyond short benchmark names and https sources. The collector
    keeps a transcription only once this accepts it, and the refresh validator
    (update/automation_integrity.py) holds every automated change to it."""
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "about", "models"}:
        raise ValueError("launch_tables_structure")
    if doc["schema_version"] != 1 or not isinstance(doc["about"], str):
        raise ValueError("launch_tables_structure")
    models = doc["models"]
    if not isinstance(models, dict) or len(models) > 200:
        raise ValueError("launch_tables_structure")
    for mid, entry in models.items():
        if not isinstance(mid, str) or mid not in catalog_ids:
            raise ValueError("launch_tables_identity")
        if not isinstance(entry, dict) or not set(entry) <= _ENTRY_KEYS:
            raise ValueError("launch_tables_entry")
        _date(entry.get("release_date"), "date")
        if "checked_on" in entry:
            _date(entry["checked_on"], "date")
        attempts = entry.get("attempts", 0)
        if type(attempts) is not int or not 0 <= attempts <= 20:
            raise ValueError("launch_tables_entry")
        tables = entry.get("tables")
        if not isinstance(tables, list) or len(tables) > 8:
            raise ValueError("launch_tables_entry")
        for table in tables:
            _check_table(mid, table, roster)


def _check_table(model_id: str, table: Any, roster: set[str]) -> None:
    if not isinstance(table, dict) or set(table) != _TABLE_KEYS:
        raise ValueError("launch_tables_table")
    source = table["source"]
    if not isinstance(source, str) or len(source) > 300 or not _URL.fullmatch(source):
        raise ValueError("launch_tables_source")
    columns = table["columns"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= 16:
        raise ValueError("launch_tables_table")
    for col in columns:
        if col is not None and (not isinstance(col, str) or not _ID.fullmatch(col)):
            raise ValueError("launch_tables_column")
        if col is not None and col not in roster and col != model_id:
            raise ValueError("launch_tables_column")
    if columns.count(model_id) != 1:
        raise ValueError("launch_tables_own_column")
    rows = table["rows"]
    if not isinstance(rows, list) or len(rows) > 80:
        raise ValueError("launch_tables_table")
    for row in rows:
        if (
            not isinstance(row, dict)
            or not set(row) <= _ROW_KEYS
            or not {"benchmark", "values"} <= set(row)
        ):
            raise ValueError("launch_tables_row")
        if not isinstance(row["benchmark"], str) or not _TEXT.fullmatch(row["benchmark"]):
            raise ValueError("launch_tables_row")
        values = row["values"]
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError("launch_tables_row")
        for v in values:
            if v is not None and (_number(v) is None or not 0 <= v <= 100 or not math.isfinite(v)):
                raise ValueError("launch_tables_value")
        if "higher_is_better" in row and not isinstance(row["higher_is_better"], bool):
            raise ValueError("launch_tables_row")
        if "component" in row and row["component"] not in COMPONENTS:
            raise ValueError("launch_tables_row")
