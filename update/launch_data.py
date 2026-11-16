"""Typed checks for the launch-table data a refresh may change.

Two files feed roadmodel's day-one AA Index estimate (src/roadmodel/estimate.py)
and the letters derived from it (update/derive_ratings.py):

* update/launch-tables.json: each vendor's launch-day benchmark table, written
  by update/collect_launch_tables.py from an Opus transcription.
* docs/index-estimates.json: the estimates update/build_index_estimates.py
  derives from it.

Both are plain data: model ids from the roster, percentages, short benchmark
names and https sources, nothing an engine reads as instructions. The
collector checks a transcription here before keeping it, and the refresh
validator (update/automation_integrity.py) runs the same checks on every
automated change, so update-launch-tables.yml merges with no human step. This
module is a validator file (scripts/security_catalog.py): standard library
only, and it never imports the estimator it checks.
"""

from __future__ import annotations

import datetime
import math
import re
from typing import Any

# The index components a launch-table row may be tagged with, and the figures
# an estimate may carry (benchmarks.json keys, as fractions).
COMPONENTS = ("hle", "terminalbench_v4_0")
FIGURES = ("hle", "lcr", "scicode", "terminalbench_v4_0")
METHODS = frozenset({"anchors", "components", "anchors+components", "other-tables"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


_ID = re.compile(r"[a-z0-9][a-z0-9.\-]{0,63}")
_TEXT = re.compile(r"[^\x00-\x1f<>\"`\\]{1,120}")
_URL = re.compile(r"https://[A-Za-z0-9.\-]+(?:/[^\s<>\"`\\]*)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ENTRY_KEYS = frozenset({"release_date", "tables", "checked_on", "attempts", "spent_usd"})
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
    (update/automation_integrity.py) holds every automated change to it.
    ``spent_usd`` is the collector's ledger: what the model's tries cost."""
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
        spent = entry.get("spent_usd", 0)
        if _number(spent) is None or not 0 <= spent <= 100:
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


_ESTIMATE_KEYS = frozenset(
    {"index", "band", "method", "anchors", "rows", "effort", "via", "figures"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LEVEL = re.compile(r"[a-z]{2,12}")


def check_index_estimates(doc: Any, roster: set[str], catalog_ids: set[str]) -> None:
    """Raise ValueError unless ``doc`` is a well-formed docs/index-estimates.json:
    one entry per catalog model, an index and its band in index points, a known
    method, anchors and placing launches named by roster ids, an effort level
    name, and figures as fractions."""
    if not isinstance(doc, dict) or set(doc) != {
        "schema_version",
        "about",
        "launch_tables_sha256",
        "models",
    }:
        raise ValueError("index_estimates_structure")
    if doc["schema_version"] != 1 or not isinstance(doc["about"], str):
        raise ValueError("index_estimates_structure")
    if not isinstance(doc["launch_tables_sha256"], str) or not _SHA256.fullmatch(
        doc["launch_tables_sha256"]
    ):
        raise ValueError("index_estimates_structure")
    models = doc["models"]
    if not isinstance(models, dict) or len(models) > 200:
        raise ValueError("index_estimates_structure")
    for mid, e in models.items():
        if not isinstance(mid, str) or mid not in catalog_ids:
            raise ValueError("index_estimates_identity")
        if not isinstance(e, dict) or not {"index", "band", "method"} <= set(e) <= _ESTIMATE_KEYS:
            raise ValueError("index_estimates_entry")
        index, band = _number(e["index"]), _number(e["band"])
        if index is None or not 0 <= index <= 100 or band is None or not 0 < band <= 20:
            raise ValueError("index_estimates_value")
        if e["method"] not in METHODS:
            raise ValueError("index_estimates_entry")
        rows = e.get("rows", 0)
        if type(rows) is not int or not 0 <= rows <= 1000:
            raise ValueError("index_estimates_entry")
        effort = e.get("effort")
        if effort is not None and (not isinstance(effort, str) or not _LEVEL.fullmatch(effort)):
            raise ValueError("index_estimates_entry")
        for key in ("anchors", "via"):
            ids = e.get(key, [])
            if not isinstance(ids, list) or len(ids) > 64:
                raise ValueError("index_estimates_entry")
            if any(not isinstance(i, str) or i not in roster for i in ids):
                raise ValueError("index_estimates_identity")
        figures = e.get("figures", {})
        if not isinstance(figures, dict) or not set(figures) <= set(FIGURES):
            raise ValueError("index_estimates_entry")
        for v in figures.values():
            if (n := _number(v)) is None or not 0 <= n <= 1:
                raise ValueError("index_estimates_value")
