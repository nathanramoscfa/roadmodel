"""A day-one estimate of an unmeasured model's AA Intelligence Index.

Artificial Analysis measures a new model days or weeks after it launches. Until
it does, roadmodel estimates the index from the model's own launch table: the
vendor sets the new model beside older ones on the same benchmarks, run the
same way, and the older columns Artificial Analysis has measured place the new
model on the index's scale. Two methods, averaged when both apply:

* Launch-table anchors. Each benchmark row with two or more anchors (measured
  models released before this one) maps that row's scores onto the index: a
  least-squares line across three or more anchors, the line through their
  spread otherwise. The median over the rows is this method's figure.
* Index components. When the launch table reports Humanity's Last Exam without
  tools or Terminal-Bench 4.0, two of the index's own components, a fit of the
  index on Artificial Analysis's measurements of those components and the
  release date places the model.

Their average, less the launch-table optimism of the model's maker (vendors
lead with the benchmarks their new model wins, and some lead harder than
others: ``MAKER_OPTIMISM``), is the estimate. Calibrated by leave-one-out over
the 26 models Artificial Analysis has measured whose launch tables place them
(2026-11): a typical miss of 2.4 index points and a root-mean-square miss of
3.5, against 2.5 and 3.8 when every maker takes the same correction. ``BAND``
is that error.

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

from roadmodel import series as _series

INDEX_KEY: Final = "artificial_analysis_intelligence_index"

# Mean amount a launch table's estimate overshoots Artificial Analysis's later
# measurement, over every maker: vendors choose the benchmarks they lead with.
# The correction for a maker with no measured launch table behind it yet.
OPTIMISM: Final = 1.6
# Makers' launch tables do not overshoot alike: each maker's own record
# corrects its estimates, trusted in proportion to how much of it there is
# (empirical-Bayes partial pooling toward the all-maker figure: a maker with n
# measured launches keeps n / (n + k) of its own mean overshoot, where k is the
# within-maker variance over the between-maker variance, never below 3, so one
# launch counts a quarter and three count half). Index points for the index,
# percentage points for a letter figure; keyed by maker(). Leave-one-out over
# the measured models' launch tables (2026-11), root-mean-square miss against
# one correction for every maker: index 3.49 against 3.77, HLE 4.45 against
# 4.75, AA-LCR 3.18 against 3.46; trained only on the launches released before
# each model, 3.90 against 4.00, 4.82 against 4.82 and 3.17 against 3.35.
# SciCode shows no difference between makers and Terminal-Bench 4.0 none that
# predicts (10.00 against 9.63), so both keep FIGURE_OPTIMISM alone.
MAKER_OPTIMISM: Final = {
    INDEX_KEY: {
        "anthropic": 0.9,
        "deepseek": 3.5,
        "google": 2.2,
        "meta": 1.9,
        "moonshot": 3.1,
        "openai": -0.9,
        "xai": 2.4,
        "zai": 1.0,
    },
    "hle": {
        "anthropic": 2.2,
        "deepseek": 5.8,
        "google": 2.4,
        "meta": 4.9,
        "moonshot": 4.5,
        "openai": 1.4,
        "xai": 5.7,
        "zai": 4.7,
    },
    "lcr": {
        "anthropic": 0.5,
        "deepseek": 0.9,
        "google": 1.5,
        "meta": 1.2,
        "moonshot": -2.3,
        "openai": 1.2,
        "xai": 2.8,
        "zai": 1.5,
    },
}
# Leave-one-out error of the maker-corrected estimate (RMSE, index points);
# neither the maker, the row count nor the rows' spread predicted a model's
# miss well enough to widen or narrow it (Gaussian log score, leave-one-out).
BAND: Final = 3.5
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
# Single-anchor pairwise slope (index points per benchmark percentage point,
# calibrated leave-one-out over 32 measured launch tables) and per-figure slopes
# for launch tables that compare against only one measured anchor.
PAIR_SLOPE: Final = 0.28
PAIR_BAND: Final = 4.5
PAIR_METHOD: Final = "pairwise"
PAIR_FIGURE_SLOPE: Final[dict[str, float]] = {
    "hle": 0.26,
    "lcr": 0.08,
    "scicode": 0.13,
    "terminalbench_v4_0": 0.35,
}
CHAIN_BAND: Final = 5.0
CHAIN_METHOD: Final = "chained"
PREDECESSOR_BAND: Final = 5.0
PREDECESSOR_METHOD: Final = "predecessor"
PRIOR_BAND: Final = 6.0
PRIOR_METHOD: Final = "prior"
OWN_METHODS: Final = frozenset(
    {"anchors", "components", "anchors+components", PAIR_METHOD, f"{PAIR_METHOD}+components"}
)
METHODS: Final = OWN_METHODS | {OTHER_METHOD, CHAIN_METHOD, PREDECESSOR_METHOD, PRIOR_METHOD}
# The four figures besides the index that update/derive_ratings.py letters a
# model on (benchmarks.json keys), each with its launch-table optimism in
# percentage points: the mean overshoot of the later measurement, leave-one-out
# over the measured models' launch tables (2026-11; 26 tables, 22 for SciCode and
# Terminal-Bench 4.0). Typical misses after it: HLE 3.9, AA-LCR 2.2, SciCode 3.3,
# Terminal-Bench 4.0 7.8 points. Means and trimmed means of the rows tied the
# median on all four but Terminal-Bench 4.0, where the median is clearly best
# (7.8 against 9.0). The all-maker correction: MAKER_OPTIMISM refines HLE and
# AA-LCR by maker. Lettered with the derivation's own rules, the estimates give
# the exact letter 96 times in 122 and an S to 22 of the 29 true S models.
FIGURE_OPTIMISM: Final = {"hle": 3.6, "lcr": 0.9, "scicode": 2.4, "terminalbench_v4_0": 4.2}
# The index components a launch table can report, by their benchmarks.json key.
# CORE_COMPONENTS are combined with anchor/pairwise estimates; the remaining
# proxy components stand in when a model lacks comparison anchors.
CORE_COMPONENTS: Final = ("hle", "terminalbench_v4_0")
COMPONENTS: Final = ("hle", "terminalbench_v4_0", "scicode", "terminalbench_v2_1", "gpqa")
# Ridge strength for the component and prior fits, on standardized inputs.
_RIDGE: Final = 0.1
_PRIOR_RIDGE: Final = 0.2
_PAIR_DELTA_CAP: Final = 25.0
_MULTIMODAL_BENCH_RE: Final = re.compile(
    r"mmmu|chartography|lvbench|mathvista|omnidoc|videomme|screenspot|docvqa",
    re.IGNORECASE,
)
_VARIANT_SUFFIX_RE: Final = re.compile(r"-(?:max|plus|fast)$")
_LETTER_POINTS: Final[dict[str, float]] = {"S": 4.0, "A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}
_MULTIMODAL_POINTS: Final[dict[str, float]] = {
    "S": 90.0,
    "A": 78.0,
    "B": 55.0,
    "C": 35.0,
    "D": 15.0,
}
_CATEGORIES: Final = (
    "coding",
    "planning",
    "agentic",
    "multimodal",
    "long-context",
    "knowledge",
    "speed",
)
_DERIVED_CATEGORIES: Final = ("coding", "planning", "agentic", "long-context", "knowledge")
# Who makes a model, from its id (update/stale_claims.py maker_of's rules, which
# a test holds this to). Order matters: gpt-oss is OpenAI's before "gpt" is.
_MAKER_RULES: Final = (
    (re.compile(r"gpt-oss"), "openai"),
    (re.compile(r"claude|opus|sonnet|haiku|fable"), "anthropic"),
    (re.compile(r"gpt"), "openai"),
    (re.compile(r"gemini"), "google"),
    (re.compile(r"grok"), "xai"),
    (re.compile(r"deepseek"), "deepseek"),
    (re.compile(r"mistral|codestral"), "mistral"),
    (re.compile(r"glm"), "zai"),
    (re.compile(r"composer"), "cursor"),
    (re.compile(r"kimi"), "moonshot"),
    (re.compile(r"muse"), "meta"),
)


def maker(model_id: str) -> str | None:
    """The company that makes ``model_id``, or None when no rule names it."""
    s = model_id.lower()
    return next((name for rx, name in _MAKER_RULES if rx.search(s)), None)


def optimism(key: str, model_id: str) -> float:
    """The launch-table optimism taken off ``model_id``'s estimate of ``key``:
    its maker's (MAKER_OPTIMISM), else the all-maker figure."""
    by_maker = MAKER_OPTIMISM.get(key, {})
    who = maker(model_id)
    if who is not None and who in by_maker:
        return by_maker[who]
    return OPTIMISM if key == INDEX_KEY else FIGURE_OPTIMISM[key]


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
    # benchmarks.json), from its own launch table or fallbacks.
    figures: dict[str, float] = field(default_factory=dict)
    # Estimated non-derived category letters ("multimodal", "speed").
    letters: dict[str, str] = field(default_factory=dict)

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
        if self.letters:
            out["letters"] = dict(sorted(self.letters.items()))
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


def _table_rows(
    model_id: str,
    entry: Mapping[str, Any],
    bench: Mapping[str, Any],
    key: str = INDEX_KEY,
    *,
    min_anchors: int = 2,
) -> list[tuple[float, dict[str, float]]]:
    """Each usable row from ``entry`` with at least ``min_anchors`` earlier
    measured columns."""
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
            if len(anchors) >= min_anchors and row_key not in seen:
                seen.add(row_key)
                out.append((sign * score, anchors))
    return out


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
    return _table_rows(model_id, entry, bench, key, min_anchors=2)


def pair_rows(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any], key: str = INDEX_KEY
) -> list[tuple[float, dict[str, float]]]:
    """Each usable row with one or more earlier measured anchors."""
    return _table_rows(model_id, entry, bench, key, min_anchors=1)


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
    """The anchor method's figure (before the optimism correction), its anchors
    and its row count; None below the floor."""
    rows = anchor_rows(model_id, entry, bench)
    index = {a: v for _, anchors in rows for a in anchors if (v := _measured(bench, a)) is not None}
    estimates = [
        e for score, anchors in rows if (e := row_estimate(score, anchors, index)) is not None
    ]
    names = tuple(sorted({a for _, anchors in rows for a in anchors}))
    if len(estimates) < MIN_ROWS or len(names) < MIN_ANCHORS:
        return None
    return statistics.median(estimates), names, len(estimates)


def _pair_values(
    rows: list[tuple[float, dict[str, float]]],
    bench: Mapping[str, Any],
    key: str,
    slope: float,
) -> tuple[list[float], tuple[str, ...]]:
    placed: list[float] = []
    names: set[str] = set()
    for score, anchors in rows:
        for anchor, xa in anchors.items():
            if (ya := _value(bench, anchor, key)) is None:
                continue
            delta = max(-_PAIR_DELTA_CAP, min(_PAIR_DELTA_CAP, slope * (score - xa)))
            placed.append(ya + delta)
            names.add(anchor)
    return placed, tuple(sorted(names))


def from_pairwise(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]
) -> tuple[float, tuple[str, ...], int] | None:
    """The 1-anchor pairwise figure (before optimism correction), its anchors,
    and row count; None below MIN_ROWS distinct benchmark rows."""
    rows = pair_rows(model_id, entry, bench)
    if len(rows) < MIN_ROWS:
        return None
    placed, names = _pair_values(rows, bench, INDEX_KEY, PAIR_SLOPE)
    if len(placed) < MIN_ROWS or not names:
        return None
    return statistics.median(placed), names, len(rows)


def figures(model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]) -> dict[str, float]:
    """Each letter figure (FIGURE_OPTIMISM) the launch table places, as a
    fraction: its rows mapped through multi-anchor rows when available, else
    1-anchor pairwise rows, less the figure's optimism for the model's maker
    (:func:`optimism`). A figure below the floors is left out."""
    out: dict[str, float] = {}
    for key in FIGURE_OPTIMISM:
        rows = anchor_rows(model_id, entry, bench, key)
        values = {
            a: v for _, anchors in rows for a in anchors if (v := _value(bench, a, key)) is not None
        }
        placed = [
            e for score, anchors in rows if (e := row_estimate(score, anchors, values)) is not None
        ]
        names = {a for _, anchors in rows for a in anchors}
        if len(placed) >= MIN_ROWS and len(names) >= MIN_ANCHORS:
            value = statistics.median(placed) - optimism(key, model_id)
            out[key] = round(min(1.0, max(0.0, value / 100)), 4)
            continue
        p_rows = pair_rows(model_id, entry, bench, key)
        if len(p_rows) < MIN_ROWS:
            continue
        p_placed, _ = _pair_values(p_rows, bench, key, PAIR_FIGURE_SLOPE[key])
        if len(p_placed) < MIN_ROWS:
            continue
        value = statistics.median(p_placed) - optimism(key, model_id)
        out[key] = round(min(1.0, max(0.0, value / 100)), 4)
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


def _ridge_predict(
    train: list[tuple[list[float], float]], point: list[float], ridge: float = _RIDGE
) -> float | None:
    """Standardized ridge regression prediction from ``train`` at ``point``."""
    if not train:
        return None
    n = len(train)
    k = len(point)
    mu = [statistics.fmean(x[j] for x, _ in train) for j in range(k)]
    sd = [statistics.pstdev([x[j] for x, _ in train]) or 1.0 for j in range(k)]
    z = [[(x[j] - mu[j]) / sd[j] for j in range(k)] for x, _ in train]
    ybar = statistics.fmean(y for _, y in train)
    yc = [y - ybar for _, y in train]
    gram = [
        [sum(r[p] * r[q] for r in z) + (ridge * n if p == q else 0.0) for q in range(k)]
        for p in range(k)
    ]
    beta = _solve(gram, [sum(r[p] * y for r, y in zip(z, yc, strict=True)) for p in range(k)])
    return ybar + sum(b * (point[j] - mu[j]) / sd[j] for j, b in enumerate(beta))


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
    model_id: str,
    entry: Mapping[str, Any],
    bench: Mapping[str, Any],
    *,
    allowed: tuple[str, ...] = COMPONENTS,
) -> float | None:
    """The component estimate: the index fitted on Artificial Analysis's own
    measurements of the reported components and the release date."""
    reported = components_reported(model_id, entry)
    released = entry.get("release_date")
    if not reported or not isinstance(released, str):
        return None
    features = [k for k in allowed if k in reported]
    if not features:
        return None
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
    if len(train) < 3 * len(point) + 3:
        return None
    return _ridge_predict(train, point, _RIDGE)


def estimate(model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]) -> Estimate | None:
    """The model's estimated index from multi-anchor comparison and/or components."""
    anchored = from_anchors(model_id, entry, bench)
    component = from_components(
        model_id,
        entry,
        bench,
        allowed=CORE_COMPONENTS if anchored is not None else COMPONENTS,
    )
    parts = [p for p in (anchored[0] if anchored else None, component) if p is not None]
    if not parts:
        return None
    method = "+".join(
        name
        for name, part in (("anchors", anchored), ("components", component))
        if part is not None
    )
    # The optimism was measured on estimates the anchors take part in; the
    # component fit alone keeps the vendor's reported components as they are.
    correction = optimism(INDEX_KEY, model_id) if anchored else 0.0
    return Estimate(
        index=round(statistics.fmean(parts) - correction, 1),
        band=BAND,
        method=method,
        anchors=anchored[1] if anchored else (),
        rows=anchored[2] if anchored else 0,
        figures=figures(model_id, entry, bench),
    )


def estimate_pairwise(
    model_id: str, entry: Mapping[str, Any], bench: Mapping[str, Any]
) -> Estimate | None:
    """The model's estimated index from 1-anchor pairwise comparison, optionally
    combined with core index components."""
    paired = from_pairwise(model_id, entry, bench)
    if paired is None:
        return None
    component = from_components(model_id, entry, bench, allowed=CORE_COMPONENTS)
    parts = [paired[0]] + ([component] if component is not None else [])
    method = f"{PAIR_METHOD}+components" if component is not None else PAIR_METHOD
    correction = optimism(INDEX_KEY, model_id)
    return Estimate(
        index=round(statistics.fmean(parts) - correction, 1),
        band=PAIR_BAND,
        method=method,
        anchors=paired[1],
        rows=paired[2],
        figures=figures(model_id, entry, bench),
    )


def _other_table_rows(
    model_id: str,
    tables: Mapping[str, Any],
    bench: Mapping[str, Any],
    key: str = INDEX_KEY,
    *,
    min_anchors: int = 2,
) -> list[tuple[float, dict[str, float], str]]:
    """Each usable row of another model's launch table listing ``model_id``
    with at least ``min_anchors`` measured competitors."""
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
                and _value(bench, col, key) is not None
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
                row_key = (re.sub(r"\W+", "", str(row.get("benchmark", "")).lower()), max(own))
                if len(anchors) >= min_anchors and row_key not in seen:
                    seen.add(row_key)
                    out.append((max(own), anchors, owner))
    return out


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
    return _other_table_rows(model_id, tables, bench, INDEX_KEY, min_anchors=2)


def other_pair_rows(
    model_id: str, tables: Mapping[str, Any], bench: Mapping[str, Any], key: str = INDEX_KEY
) -> list[tuple[float, dict[str, float], str]]:
    """Each usable row of another model's launch table with one or more anchors."""
    return _other_table_rows(model_id, tables, bench, key, min_anchors=1)


def _other_figures(
    model_id: str, tables: Mapping[str, Any], bench: Mapping[str, Any]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in FIGURE_OPTIMISM:
        rows = _other_table_rows(model_id, tables, bench, key, min_anchors=2)
        values = {
            a: v
            for _, anchors, _ in rows
            for a in anchors
            if (v := _value(bench, a, key)) is not None
        }
        placed = [
            e
            for score, anchors, _ in rows
            if (e := row_estimate(score, anchors, values)) is not None
        ]
        names = {a for _, anchors, _ in rows for a in anchors}
        if len(placed) >= MIN_ROWS and len(names) >= MIN_ANCHORS:
            value = statistics.median(placed) - OTHER_OPTIMISM
            out[key] = round(min(1.0, max(0.0, value / 100)), 4)
            continue
        p_rows = other_pair_rows(model_id, tables, bench, key)
        if len(p_rows) < MIN_ROWS:
            continue
        pair_placed, _ = _pair_values(
            [(score, anchors) for score, anchors, _ in p_rows], bench, key, PAIR_FIGURE_SLOPE[key]
        )
        if len(pair_placed) < MIN_ROWS:
            continue
        value = statistics.median(pair_placed) - OTHER_OPTIMISM
        out[key] = round(min(1.0, max(0.0, value / 100)), 4)
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
        figures=_other_figures(model_id, tables, bench),
    )


def from_other_pairwise(
    model_id: str, tables: Mapping[str, Any], bench: Mapping[str, Any]
) -> Estimate | None:
    """1-anchor fallback across other models' launch tables."""
    rows = other_pair_rows(model_id, tables, bench)
    if len(rows) < MIN_ROWS:
        return None
    placed: list[tuple[float, str]] = []
    names: set[str] = set()
    via: list[str] = []
    for score, anchors, owner in rows:
        for anchor, xa in anchors.items():
            if (ya := _measured(bench, anchor)) is None:
                continue
            delta = max(-_PAIR_DELTA_CAP, min(_PAIR_DELTA_CAP, PAIR_SLOPE * (score - xa)))
            placed.append((ya + delta, owner))
            names.add(anchor)
            if owner not in via:
                via.append(owner)
    if len(placed) < MIN_ROWS or not names:
        return None
    return Estimate(
        index=round(statistics.median(e for e, _ in placed) - OTHER_OPTIMISM, 1),
        band=OTHER_BAND,
        method=OTHER_METHOD,
        anchors=tuple(sorted(names)),
        rows=len(rows),
        via=tuple(via),
        figures=_other_figures(model_id, tables, bench),
    )


def _find_predecessor(model_id: str, candidates: set[str]) -> str | None:
    older = [o for o in candidates if o != model_id and _series.is_newer(o, model_id)]
    if older:
        return max(older, key=lambda o: (_series.version(o), o))
    stripped = _VARIANT_SUFFIX_RE.sub("", model_id)
    if stripped != model_id and stripped in candidates:
        return stripped
    return None


def from_predecessor(
    model_id: str, bench: Mapping[str, Any], prior_estimates: Mapping[str, Estimate]
) -> Estimate | None:
    """Place an unmeasured model with no table on its newest predecessor,
    offset by half the band so its ranked score preserves the predecessor's."""
    pool = {m for m in bench if _measured(bench, m) is not None} | set(prior_estimates)
    pred = _find_predecessor(model_id, pool)
    if pred is None:
        return None
    if (measured := _measured(bench, pred)) is not None:
        base_idx = measured
        evals = (bench[pred] or {}).get("evaluations") or {}
        figs = {
            k: round(float(v), 4)
            for k in FIGURE_OPTIMISM
            if (v := _number(evals.get(k))) is not None
        }
    else:
        p_est = prior_estimates[pred]
        base_idx = p_est.index - round(p_est.band / 2, 1)
        figs = dict(p_est.figures)
    index = round(min(100.0, max(0.0, base_idx + round(PREDECESSOR_BAND / 2, 1))), 1)
    return Estimate(
        index=index,
        band=PREDECESSOR_BAND,
        method=PREDECESSOR_METHOD,
        anchors=(pred,),
        rows=0,
        figures=figs,
    )


def _blended_price(model: Mapping[str, Any]) -> float | None:
    in_p = _number(model.get("input_price_per_1m"))
    out_p = _number(model.get("output_price_per_1m"))
    if in_p is None or out_p is None:
        return None
    bp = (3.0 * in_p + out_p) / 4.0
    return bp if bp > 0 else None


def from_prior(
    model_id: str,
    model: Mapping[str, Any],
    bench: Mapping[str, Any],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> Estimate | None:
    """Calibrated fallback from curated letters + price, or price + release
    date when only placeholder B letters exist."""
    bp = _blended_price(model)
    if bp is None:
        return None
    tiers = model.get("tiers") or {}
    derived_tiers = {str(tiers.get(c, "B")) for c in _DERIVED_CATEGORIES}
    curated = derived_tiers != {"B"} and not model.get("added_on")

    measured_models: list[tuple[str, Mapping[str, Any], float, float]] = []
    for cid, row in sorted(catalog_by_id.items()):
        idx = _measured(bench, cid)
        cbp = _blended_price(row)
        if idx is not None and cbp is not None:
            measured_models.append((cid, row, cbp, idx))
    if not measured_models:
        return None

    if curated:
        train = [
            (
                [math.log10(cbp)]
                + [
                    _LETTER_POINTS.get(str((row.get("tiers") or {}).get(c, "B")), 2.0)
                    for c in _DERIVED_CATEGORIES
                ],
                idx,
            )
            for _, row, cbp, idx in measured_models
        ]
        point = [math.log10(bp)] + [
            _LETTER_POINTS.get(str(tiers.get(c, "B")), 2.0) for c in _DERIVED_CATEGORIES
        ]
        pred = (
            _ridge_predict(train, point, _PRIOR_RIDGE)
            if len(train) >= 5
            else statistics.fmean(y for _, y in train)
        )
        if pred is None:
            return None
        return Estimate(
            index=round(min(95.0, max(5.0, pred)), 1),
            band=PRIOR_BAND,
            method=PRIOR_METHOD,
            anchors=(),
            rows=0,
        )

    dates = [d for cid, _, _, _ in measured_models if (d := _release(bench, cid)) is not None]
    min_y = min((_years(d) for d in dates), default=0.0)
    max_y = max((_years(d) for d in dates), default=1.5)
    train_p = [
        (
            [math.log10(cbp), _years(d)],
            idx,
        )
        for cid, _, cbp, idx in measured_models
        if (d := _release(bench, cid)) is not None
    ]
    raw_date = str(model.get("added_on") or "")
    target_y = _years(raw_date) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) else max_y
    target_y = max(min_y, min(max_y + 0.25, target_y))
    if len(train_p) >= 5:
        pred = _ridge_predict(train_p, [math.log10(bp), target_y], _PRIOR_RIDGE)
    else:
        pred = statistics.fmean(y for _, _, _, y in measured_models)
    if pred is None:
        return None
    clamped_idx = round(min(95.0, max(5.0, pred)), 1)
    figs: dict[str, float] = {}
    for key in FIGURE_OPTIMISM:
        f_train = [
            ([idx, math.log10(cbp)], val / 100.0)
            for cid, _, cbp, idx in measured_models
            if (val := _value(bench, cid, key)) is not None
        ]
        if len(f_train) >= 5:
            f_pred = _ridge_predict(f_train, [clamped_idx, math.log10(bp)], _PRIOR_RIDGE)
            if f_pred is not None:
                figs[key] = round(min(1.0, max(0.0, f_pred)), 4)
    return Estimate(
        index=clamped_idx,
        band=PRIOR_BAND,
        method=PRIOR_METHOD,
        anchors=(),
        rows=0,
        figures=figs,
    )


def estimated_extra_letters(
    model_id: str,
    model: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    bench: Mapping[str, Any],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
    est: Estimate,
) -> dict[str, str]:
    """Estimated ``multimodal`` and ``speed`` letters for an unmeasured model,
    leaving existing curated or inherited letters intact."""
    out: dict[str, str] = {}
    tiers = model.get("tiers") or {}
    measured_or_series = {m for m in bench if _measured(bench, m) is not None}

    # Multimodal: relative placement on vision/chart/video launch rows against
    # measured models or models with a measured same-series predecessor.
    mm_vals: list[float] = []
    if isinstance(entry, Mapping):
        for table in entry.get("tables") or []:
            columns = list(table.get("columns") or [])
            if model_id not in columns:
                continue
            own = columns.index(model_id)
            for row in table.get("rows") or []:
                if not _MULTIMODAL_BENCH_RE.search(str(row.get("benchmark", ""))):
                    continue
                values = list(row.get("values") or [])
                if len(values) != len(columns) or (own_score := _number(values[own])) is None:
                    continue
                if any((v := _number(x)) is not None and not 0 <= v <= 100 for x in values):
                    continue
                sign = 1.0 if row.get("higher_is_better", True) else -1.0
                for i, col in enumerate(columns):
                    if i == own or not isinstance(col, str) or col not in catalog_by_id:
                        continue
                    peer = catalog_by_id[col]
                    if (
                        _measured(bench, col) is None
                        and _find_predecessor(col, measured_or_series) is None
                    ):
                        continue
                    peer_mm = str((peer.get("tiers") or {}).get("multimodal", ""))
                    if (
                        peer_mm not in _MULTIMODAL_POINTS
                        or (peer_score := _number(values[i])) is None
                    ):
                        continue
                    delta = max(
                        -_PAIR_DELTA_CAP,
                        min(_PAIR_DELTA_CAP, 0.8 * sign * (own_score - peer_score)),
                    )
                    mm_vals.append(_MULTIMODAL_POINTS[peer_mm] + delta)
    if mm_vals:
        med = statistics.median(mm_vals)
        if med >= 82.5:
            out["multimodal"] = "S"
        elif med >= 65.0:
            out["multimodal"] = "A"
        elif med >= 45.0:
            out["multimodal"] = "B"
        elif med >= 25.0:
            out["multimodal"] = "C"
        else:
            out["multimodal"] = "D"

    has_pred = _find_predecessor(model_id, set(catalog_by_id) | set(bench)) is not None
    if not has_pred:
        if (
            not mm_vals
            and est.method == PRIOR_METHOD
            and est.index >= 50.0
            and maker(model_id) in {"google", "anthropic", "openai"}
            and str(tiers.get("multimodal", "B")) in {"B", "A"}
        ):
            out["multimodal"] = "A"
        cur_speed = str(tiers.get("speed", "B"))
        out_p = _number(model.get("output_price_per_1m"))
        if out_p is not None:
            if out_p < 8.0 and not model.get("always_thinks") and cur_speed in {"B", "A"}:
                out["speed"] = "A"
            elif out_p >= 25.0 and cur_speed in {"B", "D"}:
                out["speed"] = "D"
    return out


def _place_from_tables(
    model_id: str,
    tables: Mapping[str, Any],
    bench: Mapping[str, Any],
) -> Estimate | None:
    entry = tables.get(model_id)
    if isinstance(entry, Mapping) and (est := estimate(model_id, entry, bench)) is not None:
        return est
    if (est := from_other_tables(model_id, tables, bench)) is not None:
        return est
    if (
        isinstance(entry, Mapping)
        and (est := estimate_pairwise(model_id, entry, bench)) is not None
    ):
        return est
    return from_other_pairwise(model_id, tables, bench)


def estimate_all(
    tables: Mapping[str, Any],
    bench: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Estimate]:
    """An estimate for every unmeasured model: launch tables (multi-anchor,
    cross-table, 1-anchor pairwise, chained second pass), then predecessor and
    calibrated market/letter priors when ``catalog`` is provided."""
    named = set(tables)
    for entry in tables.values():
        for table in (entry.get("tables") or []) if isinstance(entry, Mapping) else []:
            named |= {c for c in table.get("columns") or [] if isinstance(c, str)}

    out: dict[str, Estimate] = {}
    for model_id in sorted(named):
        if _measured(bench, model_id) is not None:
            continue
        if (est := _place_from_tables(model_id, tables, bench)) is not None:
            out[model_id] = est

    # Pass 2: chain newly placed estimates as anchors for remaining table models.
    for _ in range(2):
        augmented: dict[str, Any] = dict(bench)
        for mid, est in out.items():
            entry = tables.get(mid)
            rel = str(
                (entry.get("release_date") if isinstance(entry, Mapping) else None)
                or _release(bench, mid)
                or "2026-01-01"
            )
            augmented[mid] = {
                "release_date": rel,
                "evaluations": {INDEX_KEY: est.index, **est.figures},
            }
        added_any = False
        for model_id in sorted(named):
            if model_id in out or _measured(bench, model_id) is not None:
                continue
            if (found := _place_from_tables(model_id, tables, augmented)) is not None:
                out[model_id] = Estimate(
                    index=found.index,
                    band=max(found.band, CHAIN_BAND),
                    method=CHAIN_METHOD,
                    anchors=found.anchors,
                    rows=found.rows,
                    via=found.via,
                    figures=found.figures,
                )
                added_any = True
        if not added_any:
            break

    if catalog is None:
        return out

    catalog_by_id: dict[str, Mapping[str, Any]] = {
        str(m["id"]): m for m in catalog.get("models", []) if isinstance(m, Mapping) and m.get("id")
    }
    for model_id in sorted(catalog_by_id):
        if model_id in out or _measured(bench, model_id) is not None:
            continue
        if (est := from_predecessor(model_id, bench, out)) is not None:
            out[model_id] = est
            continue
        if (est := from_prior(model_id, catalog_by_id[model_id], bench, catalog_by_id)) is not None:
            out[model_id] = est

    for model_id, model in catalog_by_id.items():
        if model_id not in out:
            continue
        entry = tables.get(model_id)
        extra = estimated_extra_letters(
            model_id,
            model,
            entry if isinstance(entry, Mapping) else None,
            bench,
            catalog_by_id,
            out[model_id],
        )
        if extra:
            e = out[model_id]
            out[model_id] = Estimate(
                index=e.index,
                band=e.band,
                method=e.method,
                anchors=e.anchors,
                rows=e.rows,
                via=e.via,
                figures=e.figures,
                letters=extra,
            )
    return out
