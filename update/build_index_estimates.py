#!/usr/bin/env python3
"""Write docs/index-estimates.json: a day-one AA Index estimate for each catalog
model Artificial Analysis has not measured, from its launch table (or, when
that table is too thin, from later launch tables that list it).

Inputs: update/launch-tables.json (each vendor's launch-day benchmark table,
columns as model ids) and docs/benchmarks.json (the anchors' measured index).
The method and its measured accuracy are in src/roadmodel/estimate.py. The
/models page shows each estimate, marked ≈ with its band, until Artificial
Analysis measures the model, and the scorer ranks the model on it, less half
its band (scoring.with_estimates). The package bundles the
file, and the hosted service reads main's copy (service/app/live_data.py).

    python update/build_index_estimates.py          # write
    python update/build_index_estimates.py --check  # exit 1 if the file is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from roadmodel import estimate, scoring  # noqa: E402

TABLES = REPO / "update" / "launch-tables.json"
BENCHMARKS = REPO / "docs" / "benchmarks.json"
CATALOG = REPO / "docs" / "catalog.json"
OUT = REPO / "docs" / "index-estimates.json"


def build(tables_raw: bytes, bench: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """The estimates document. Each estimate names its ``effort``: the top
    level the model's effort dials offer (scoring.top_level), the setting a
    vendor's launch table reports and the one the scorer places it at."""
    tables = json.loads(tables_raw)["models"]
    catalog_ids = {str(m["id"]) for m in catalog.get("models", []) if isinstance(m, dict)}
    estimates = {
        m: e
        for m, e in estimate.estimate_all(tables, bench, catalog=catalog).items()
        if m in catalog_ids
    }
    return {
        "schema_version": 1,
        "about": (
            "roadmodel's estimate of each unmeasured catalog model's AA Intelligence Index, "
            "from its launch table, or from later launch tables that list it when its own is "
            "too thin (src/roadmodel/estimate.py). Shown ≈ on /models until "
            "Artificial Analysis measures the model. Regenerate with "
            "update/build_index_estimates.py."
        ),
        "launch_tables_sha256": hashlib.sha256(tables_raw).hexdigest(),
        "models": {
            m: {**e.as_json(), "effort": scoring.top_level(m, catalog)}
            for m, e in estimates.items()
        },
    }


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args(argv)
    bench = json.loads(BENCHMARKS.read_text())["models"]
    catalog = json.loads(CATALOG.read_text())
    text = render(build(TABLES.read_bytes(), bench, catalog))
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python update/build_index_estimates.py")
            return 1
        return 0
    OUT.write_text(text)
    doc = json.loads(text)
    for mid, e in doc["models"].items():
        effort_part = f" at {e['effort']}" if e.get("effort") else ""
        details = [e["method"]]
        if e.get("anchors") or e.get("rows"):
            details.append(f"{len(e['anchors'])} anchors, {e['rows']} rows")
        if e.get("via"):
            details.append(f"from {', '.join(e['via'])}'s tables")
        if e.get("letters"):
            letters_str = " ".join(f"{k}={v}" for k, v in e["letters"].items())
            details.append(f"letters: {letters_str}")
        print(f"{mid}: ≈{e['index']} ±{e['band']}{effort_part} ({'; '.join(details)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
