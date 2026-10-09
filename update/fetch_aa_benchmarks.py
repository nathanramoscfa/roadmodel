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

AA measures a reasoning model at several efforts, one row each. The mapped
row stays the model's headline figure; `aa_effort` names its level, and
`effort_variants` carries the model's other levels so the scorer can read a
pick's evidence at the effort it actually runs.

Every joined row must NAME its catalog model: AA's display name carries each
token of the catalog name ("Sonnet 5.5" in "Claude Sonnet 5.5 (Adaptive
Reasoning, Max Effort)"), and AA's base name (before the parenthetical)
adds nothing but a vendor prefix, "Preview" or a date stamp. A row that fails
is dropped and listed under `mismatched`, so a wrong map entry shows dashes
on /models instead of another model's scores — a surprising number on the
page is then always AA's own figure for that model.
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

# 2: each row names the effort AA ran it at (`aa_effort`) and carries AA's
# rows for the same model at its other efforts (`effort_variants`).
SCHEMA_VERSION = 2

# Effort levels as AA names them in a row's parenthetical ("GPT-6 Luna
# (Xhigh)", "Claude Sonnet 5.5 (Adaptive Reasoning, Max Effort)"), lowest
# first. A level row's slug is the model's slug plus the level
# (`gpt-6-luna-xhigh`).
EFFORT_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")


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


def load_catalog_names() -> dict[str, str]:
    catalog = json.loads(CATALOG_PATH.read_text())
    return {m["id"]: m["name"] for m in catalog.get("models", []) if m.get("name")}


def load_map() -> dict[str, str | None]:
    raw = json.loads(MAP_PATH.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)+|[a-z]+|\d+", s.lower()))


# Words AA's base name may add to the catalog name without naming a different
# model: its vendor prefix ("Claude 4.5 Haiku" for "Haiku 4.5") and a release
# stage. A four-digit date stamp ("DeepSeek V4 Pro 0813") is allowed as well.
_BENIGN_EXTRA = frozenset({"claude", "preview"})


def names_model(catalog_name: str, aa_name: str) -> bool:
    """True when AA's display name names the catalog model: every token of the
    catalog name appears in it ("5.5" is one token, so "Sonnet 5" never matches
    "Sonnet 5.5"), and AA's base name adds no model word of its own ("GPT-5
    mini" never stands in for "GPT-5")."""
    want = _tokens(catalog_name)
    if not want or not want <= _tokens(aa_name):
        return False
    extra = _tokens(aa_name.split("(", 1)[0]) - want
    return all(t in _BENIGN_EXTRA or re.fullmatch(r"\d{4}", t) for t in extra)


def aa_effort(aa_name: str) -> str | None:
    """The effort level AA ran a row at, read from its name's parenthetical;
    None when it names none ("Reasoning", "Non-reasoning")."""
    paren = re.search(r"\(([^)]*)\)", aa_name)
    if paren is None:
        return None
    text = re.sub(r"\b(?:x-high|extra high)\b", "xhigh", paren.group(1).lower())
    return next((w for w in re.findall(r"[a-z]+", text) if w in EFFORT_LEVELS), None)


def effort_variants(
    slug: str,
    base_level: str | None,
    by_slug: dict[Any, dict[str, Any]],
    catalog_name: str | None,
) -> dict[str, Any]:
    """AA's rows for the same model at its other effort levels, keyed by level:
    the row at `<slug>-<level>` whose name says that level (and, with the name
    check on, names the catalog model). A model's benchmark scores move with
    its effort (GPT-6 Luna reads 21.5 on the AA Index at low and 38.1 at max),
    so the scorer reads a pick's evidence at the effort it runs."""
    out: dict[str, Any] = {}
    for level in EFFORT_LEVELS:
        if level == base_level:
            continue
        src = by_slug.get(f"{slug}-{level}")
        if src is None or aa_effort(src.get("name") or "") != level:
            continue
        if catalog_name and not names_model(catalog_name, src.get("name") or ""):
            continue
        evals = src.get("evaluations") or {}
        out[level] = {
            "aa_slug": src.get("slug"),
            "aa_name": src.get("name"),
            # Only measured figures: a level row is read, never shown as a column.
            "evaluations": {k: v for k, v in evals.items() if v is not None},
            "median_output_tokens_per_second": src.get("median_output_tokens_per_second"),
        }
    return out


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
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`names` ({catalog id: display name}) turns on the name check: a mapped
    row whose AA name does not name the catalog model is left out and listed
    under `mismatched`."""
    by_slug = {m.get("slug"): m for m in aa if m.get("slug")}
    models: dict[str, Any] = {}
    unmapped: list[str] = []
    missing_slugs: list[str] = []
    mismatched: list[str] = []
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
        catalog_name = (names or {}).get(cid)
        if catalog_name and not names_model(catalog_name, src.get("name") or ""):
            # The map joins this id to a different model. Its scores would sit
            # under the wrong name, so the row shows dashes until the map is fixed.
            mismatched.append(f"{cid} -> {slug} ({src.get('name')})")
            continue
        level = aa_effort(src.get("name") or "")
        variants = effort_variants(slug, level, by_slug, catalog_name)
        # The headline is the model's top measured effort, as the page and
        # the ratings read it ("its best run"). AA's default row is usually
        # that one, but not always (Grok 4.6's is High though AA measured
        # XHigh): re-base on the top level, the default row becoming a level.
        above = [
            lv for lv in variants if level and EFFORT_LEVELS.index(lv) > EFFORT_LEVELS.index(level)
        ]
        if level and above:
            top = max(above, key=EFFORT_LEVELS.index)
            evals = src.get("evaluations") or {}
            variants[level] = {
                "aa_slug": src.get("slug"),
                "aa_name": src.get("name"),
                "evaluations": {k: v for k, v in evals.items() if v is not None},
                "median_output_tokens_per_second": src.get("median_output_tokens_per_second"),
            }
            src = by_slug[variants.pop(top)["aa_slug"]]
            slug, level = str(src.get("slug")), top
            variants = dict(sorted(variants.items(), key=lambda kv: EFFORT_LEVELS.index(kv[0])))
        models[cid] = {
            "aa_id": src.get("id"),
            "aa_slug": slug,
            "aa_name": src.get("name"),
            "aa_creator": (src.get("model_creator") or {}).get("name"),
            "release_date": src.get("release_date"),
            "evaluations": src.get("evaluations") or {},
            "median_output_tokens_per_second": src.get("median_output_tokens_per_second"),
            "median_time_to_first_token_seconds": src.get("median_time_to_first_token_seconds"),
            "aa_effort": level,
            "effort_variants": variants,
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
        "mismatched": mismatched,
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

    doc = build(
        catalog_ids,
        mapping,
        aa,
        now=dt.datetime.now(dt.timezone.utc),
        names=load_catalog_names(),
    )
    for cid in doc["unmapped"]:
        print(f"::warning::{cid} has no entry in update/aa-model-map.json (run --suggest)")
    for pair in doc["missing_slugs"]:
        print(f"::warning::AA no longer serves {pair}; update update/aa-model-map.json")
    for pair in doc["mismatched"]:
        print(
            f"::warning::{pair} names a different model; its scores are left out "
            "until update/aa-model-map.json is fixed"
        )

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
