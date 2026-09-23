#!/usr/bin/env python3
"""Build docs/benchmarks.json — one lab's numbers for every catalog model.

The /models page used to mine benchmark figures out of each row's free-text
`headline_benchmarks` prose, which gave a different benchmark (and scale) per
row and a figure for only some rows. This script replaces that with a
STRUCTURED, UNIFORM layer: every value comes from Artificial Analysis's
Insights API (one lab, one methodology, one scale per column), keyed by the
catalog's own model ids through the editorial map in
`update/aa-model-map.json`.

    python update/fetch_aa_benchmarks.py            # writes docs/benchmarks.json
    python update/fetch_aa_benchmarks.py --suggest  # candidates for unmapped ids
    python update/fetch_aa_benchmarks.py --check    # exit 1 if the file is stale

Requires `AA_API_KEY` (free tier, 1000 req/day; this makes ONE request). Per
AA's terms, attribution to https://artificialanalysis.ai/ is required wherever
the data is surfaced — the page credits the source in the grid header and the
benchmark reference.

The map's values are AA slugs; `null` means "editorially confirmed: AA has not
measured this model" and is distinct from a catalog id missing from the map
entirely, which the output lists under `unmapped` so a cron-added model gets
mapped instead of silently showing dashes forever. Neither case fails the run.

The Insights API returns EVERY evaluation AA publishes for a model as
`evaluations.<key>`; this file keeps them all (nulls included) so the web
column set can grow without a re-fetch. Accuracy-style evaluations arrive as
0–1 fractions and the composite indices as 0–100; the web layer normalises
display (see web/lib/benchmark-grid.ts), this file stores the API's values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
MAP_PATH = REPO_ROOT / "update" / "aa-model-map.json"
OUT_PATH = REPO_ROOT / "docs" / "benchmarks.json"

AA_ENDPOINT = "https://artificialanalysis.ai/api/v2/data/llms/models"
AA_HOME = "https://artificialanalysis.ai/"
USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 60

SCHEMA_VERSION = 1


def fetch_aa_models(api_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        AA_ENDPOINT,
        headers={"x-api-key": api_key, "User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=FETCH_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    models = payload.get("data") or []
    if not models:
        raise RuntimeError("AA API returned no models — refusing to write an empty file.")
    return models


def load_catalog_ids() -> list[str]:
    catalog = json.loads(CATALOG_PATH.read_text())
    return [m["id"] for m in catalog.get("models", [])]


def load_map() -> dict[str, str | None]:
    raw = json.loads(MAP_PATH.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)+|[a-z]+|\d+", s.lower()))


def suggest(
    catalog_ids: list[str], mapping: dict[str, str | None], aa: list[dict[str, Any]]
) -> None:
    """Print likely AA slugs for catalog ids the map does not cover."""
    slugs = [m.get("slug") or "" for m in aa]
    for cid in catalog_ids:
        if cid in mapping:
            continue
        want = _tokens(cid)
        scored = sorted(
            slugs,
            key=lambda s: (-len(want & _tokens(s)), len(s)),
        )
        close = difflib.get_close_matches(cid, slugs, n=3, cutoff=0.5)
        picks = list(dict.fromkeys(close + scored[:5]))[:6]
        print(f"{cid}:")
        for s in picks:
            print(f"    {s}")


def _as_slug(catalog_id: str) -> str:
    """The slug AA would give a catalog id: lower case, dots as dashes
    (`grok-4.7` -> `grok-4-7`, `claude-opus-5-5` unchanged)."""
    return catalog_id.lower().replace(".", "-")


def auto_map(
    catalog_ids: list[str], mapping: dict[str, str | None], aa: list[dict[str, Any]]
) -> dict[str, str]:
    """Map a catalog id that has NO map entry to the AA model whose slug is
    exactly that id (dots as dashes). Returns only the new entries.

    A model the daily catalog refresh adds used to sit unmapped — its grid row
    all dashes, its letters inherited placeholders — until someone noticed
    (Opus 5.5 and Grok 4.7, #694). An exact slug match is the choice a person
    makes anyway; anything short of exact stays unmapped and is still
    reported, and an existing entry (a deliberate `null` included) is never
    touched."""
    slugs = {m.get("slug") for m in aa if m.get("slug")}
    return {
        cid: _as_slug(cid) for cid in catalog_ids if cid not in mapping and _as_slug(cid) in slugs
    }


def save_map(mapping: dict[str, str | None]) -> None:
    """Rewrite the map in its own layout: `_comment` first, then ids sorted."""
    raw = json.loads(MAP_PATH.read_text())
    notes = {k: v for k, v in raw.items() if k.startswith("_")}
    ordered = {**notes, **{k: mapping[k] for k in sorted(mapping)}}
    MAP_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")


def build(
    catalog_ids: list[str],
    mapping: dict[str, str | None],
    aa: list[dict[str, Any]],
    *,
    now: dt.datetime,
) -> dict[str, Any]:
    by_slug = {m.get("slug"): m for m in aa if m.get("slug")}
    models: dict[str, Any] = {}
    unmapped: list[str] = []
    missing_slugs: list[str] = []
    for cid in catalog_ids:
        if cid not in mapping:
            unmapped.append(cid)
            continue
        slug = mapping[cid]
        if slug is None:
            continue
        src = by_slug.get(slug)
        if src is None:
            # The map names a slug AA no longer serves (renamed / retired). Keep
            # the run alive — the row shows dashes — but say so loudly.
            missing_slugs.append(f"{cid} -> {slug}")
            continue
        models[cid] = {
            "aa_id": src.get("id"),
            "aa_slug": slug,
            "aa_name": src.get("name"),
            "aa_creator": (src.get("model_creator") or {}).get("name"),
            "release_date": src.get("release_date"),
            "evaluations": src.get("evaluations") or {},
            "median_output_tokens_per_second": src.get("median_output_tokens_per_second"),
            "median_time_to_first_token_seconds": src.get("median_time_to_first_token_seconds"),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "name": "Artificial Analysis",
            "url": AA_HOME,
            "endpoint": AA_ENDPOINT,
            "attribution": "Benchmark data © Artificial Analysis, used under its API terms with attribution.",
        },
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_count": len(models),
        "unmapped": unmapped,
        "missing_slugs": missing_slugs,
        "models": models,
    }


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def stable_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """Everything except the timestamp, for change detection."""
    return {k: v for k, v in doc.items() if k != "generated_at_utc"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suggest", action="store_true", help="print AA slug candidates for unmapped ids"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if docs/benchmarks.json would change"
    )
    parser.add_argument("--dump", type=Path, help="also write the raw AA payload here (debugging)")
    args = parser.parse_args()

    api_key = os.environ.get("AA_API_KEY")
    if not api_key:
        sys.stderr.write(
            "AA_API_KEY is not set. Locally: scripts/with-prod-secrets.sh (keychain "
            "roadmodel/AA_API_KEY); in CI the secret is already wired.\n"
        )
        return 2

    aa = fetch_aa_models(api_key)
    if args.dump:
        args.dump.write_text(json.dumps(aa, indent=2))
    catalog_ids = load_catalog_ids()
    mapping = load_map()

    if args.suggest:
        suggest(catalog_ids, mapping, aa)
        return 0

    if not args.check:
        added = auto_map(catalog_ids, mapping, aa)
        if added:
            mapping.update(added)
            save_map(mapping)
            for cid, slug in added.items():
                # Parsed by update-benchmarks.yml into the PR description.
                print(f"AUTO_MAPPED {cid} -> {slug}")

    doc = build(catalog_ids, mapping, aa, now=dt.datetime.now(dt.timezone.utc))
    for cid in doc["unmapped"]:
        print(f"::warning::{cid} has no entry in update/aa-model-map.json (run --suggest)")
    for pair in doc["missing_slugs"]:
        print(f"::warning::AA no longer serves {pair}; update update/aa-model-map.json")

    if args.check:
        existing = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else {}
        if stable_fields(existing) != stable_fields(doc):
            sys.stderr.write(f"{OUT_PATH.relative_to(REPO_ROOT)} is stale.\n")
            return 1
        print("up to date")
        return 0

    # Do not churn the timestamp when nothing measurable changed.
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text())
        if stable_fields(existing) == stable_fields(doc):
            print(f"{OUT_PATH.relative_to(REPO_ROOT)} unchanged ({doc['model_count']} models)")
            return 0
    OUT_PATH.write_text(render(doc))
    print(
        f"Wrote {OUT_PATH.relative_to(REPO_ROOT)} ({doc['model_count']} of {len(catalog_ids)} models measured)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
