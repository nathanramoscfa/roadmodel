"""The catalog's lifecycle rule: supersession, then retirement, applied as data.

A model is SUPERSEDED when another model in ``<model-options>``:

* has the same maker (the provider of the first-party access method that
  offers it, ``validate_catalog_conformance._model_makers``);
* costs the same or less, on the blended price (3 x input + 1 x output) / 4;
* scores higher on the Artificial Analysis Intelligence Index;
* is rated at least as high in each of the seven categories; and
* is offered by every access method that offers the model, so the newer model
  is always there to take its place.

The one with the highest AA Index (then the cheaper, then the lower id) is its
successor. A superseded model carries ``superseded-by`` and ``superseded-on``
(the day it was first superseded) in its ``<model>`` element: the recommender
leaves it out of its candidates while the successor is available, and /models
tags it. RETIRE_AFTER_DAYS later, if it is still superseded, it is RETIRED:
``retired-on`` joins the tags, and from then on it leaves ``docs/catalog.json``
(so the website and the MCP catalog drop it) and the recommender's prompt.
Retirement is sticky; the element stays in the source file as the record of
what it was and what replaced it. A model that stops meeting the test before
it retires (a price change, a benchmark update) loses its tag, and its clock
starts again if it returns.

Usage: ``python update/supersede.py --write [--today YYYY-MM-DD] [--base PATH]``
(``--base``: the committed selector, to restore tags a regenerated file
dropped). Prints one line per change for the PR body.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from build_catalog import (  # noqa: E402
    RETIRE_AFTER_DAYS,
    TASK_CATEGORIES,
    _parse_access_methods,
    _parse_attrs,
    _parse_price,
)
from selector_re import MODEL_RE  # noqa: E402
from validate_catalog_conformance import _model_makers  # noqa: E402

REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
BENCHMARKS_PATH = REPO_ROOT / "docs" / "benchmarks.json"

RATING_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_CITED_AA_RE = re.compile(r"AA Intelligence Index\s+(\d+(?:\.\d+)?)")
_TAG_ATTR_RE = re.compile(r'\s+(?:superseded-by|superseded-on|retired-on)="[^"]*"')


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    blended: float
    aa_index: float | None
    ratings: dict[str, int]
    since: str | None  # superseded-on, if tagged
    by: str | None  # superseded-by, if tagged
    retired: str | None  # retired-on, if retired


def blended_price(input_per_1m: float, output_per_1m: float) -> float:
    return (3 * input_per_1m + output_per_1m) / 4


def _aa_index(mid: str, attrs: dict[str, str], benchmarks: dict[str, Any]) -> float | None:
    """The AA snapshot's figure, else the one the catalog cites (the same
    order the /models page uses)."""
    evals = (benchmarks.get("models", {}).get(mid) or {}).get("evaluations") or {}
    measured = evals.get("artificial_analysis_intelligence_index")
    if isinstance(measured, (int, float)):
        return float(measured)
    m = _CITED_AA_RE.search(attrs.get("headline-benchmarks", ""))
    return float(m.group(1)) if m else None


def parse_models(selector_text: str, benchmarks: dict[str, Any]) -> list[Model]:
    options = _OPTIONS_RE.search(selector_text)
    if not options:
        raise ValueError("<model-options> block not found in selector text")
    out: list[Model] = []
    for m in MODEL_RE.finditer(options.group(1)):
        attrs = _parse_attrs(m.group(1))
        mid = attrs.get("id", "")
        in_p = _parse_price(attrs.get("input-price-per-1m", ""))
        out_p = _parse_price(attrs.get("output-price-per-1m", ""))
        if not mid or in_p is None or out_p is None:
            continue
        out.append(
            Model(
                id=mid,
                name=attrs.get("name", mid),
                blended=blended_price(in_p, out_p),
                aa_index=_aa_index(mid, attrs, benchmarks),
                ratings={
                    c: RATING_RANK.get(attrs.get(f"tier-{c}", ""), 0) for c in TASK_CATEGORIES
                },
                since=attrs.get("superseded-on") or None,
                by=attrs.get("superseded-by") or None,
                retired=attrs.get("retired-on") or None,
            )
        )
    return out


def successors(selector_text: str, models: list[Model]) -> dict[str, str]:
    """Each superseded model's id -> its successor's id."""
    makers = _model_makers(selector_text)
    offered: dict[str, set[str]] = {}
    for method in _parse_access_methods(selector_text):
        for mid in method.get("supports_models", []):
            offered.setdefault(str(mid), set()).add(str(method.get("id", "")))
    out: dict[str, str] = {}
    for old in models:
        maker = makers.get(old.id)
        if maker is None or old.aa_index is None:
            continue
        where = offered.get(old.id, set())
        best: Model | None = None
        for new in models:
            if new.id == old.id or new.aa_index is None or makers.get(new.id) != maker:
                continue
            if not (new.blended <= old.blended and new.aa_index > old.aa_index):
                continue
            if any(new.ratings[c] < old.ratings[c] for c in TASK_CATEGORIES):
                continue
            if not where <= offered.get(new.id, set()):
                continue
            if best is None or (-new.aa_index, new.blended, new.id) < (
                -best.aa_index,  # type: ignore[operator]
                best.blended,
                best.id,
            ):
                best = new
        if best is not None:
            out[old.id] = best.id
    return out


@dataclass(frozen=True)
class Tags:
    by: str
    since: str
    retired: str | None = None

    def attrs(self) -> str:
        out = f'superseded-by="{self.by}" superseded-on="{self.since}"'
        return out + (f' retired-on="{self.retired}"' if self.retired else "")


@dataclass
class Plan:
    tags: dict[str, Tags]  # every model that ends the run tagged
    newly: list[str]  # superseded for the first time this run
    cleared: list[str]  # no longer superseded (tag removed)
    retired: list[str]  # retired this run


def plan(
    selector_text: str,
    benchmarks: dict[str, Any],
    today: dt.date,
    base: dict[str, Tags] | None = None,
) -> Plan:
    """What each model's tags should be after this run. ``base`` holds the tags
    of the committed selector, so a tag a regenerated file dropped comes back
    with its original dates."""
    models = parse_models(selector_text, benchmarks)
    base = base or {}
    result = Plan({}, [], [], [])
    live: list[Model] = []
    for m in models:
        recorded = base.get(m.id)
        retired = m.retired or (recorded.retired if recorded else None)
        if retired:
            # Sticky: a retired model keeps its record whatever changes after.
            by = m.by or (recorded.by if recorded else "")
            since = m.since or (recorded.since if recorded else retired)
            result.tags[m.id] = Tags(by, since, retired)
        else:
            live.append(m)
    succ = successors(selector_text, live)
    for m in live:
        recorded = base.get(m.id)
        if m.id not in succ:
            if m.since or recorded:
                result.cleared.append(m.id)
            continue
        first_seen = m.since or (recorded.since if recorded else None)
        if first_seen is None:
            first_seen = today.isoformat()
            result.newly.append(m.id)
        if (today - dt.date.fromisoformat(first_seen)).days >= RETIRE_AFTER_DAYS:
            result.tags[m.id] = Tags(succ[m.id], first_seen, today.isoformat())
            result.retired.append(m.id)
        else:
            result.tags[m.id] = Tags(succ[m.id], first_seen)
    return result


def _element_spans(selector_text: str) -> dict[str, tuple[int, int]]:
    options = _OPTIONS_RE.search(selector_text)
    if options is None:
        raise ValueError("<model-options> block not found in selector text")
    base = options.start(1)
    spans: dict[str, tuple[int, int]] = {}
    for m in MODEL_RE.finditer(options.group(1)):
        mid = _parse_attrs(m.group(1)).get("id", "")
        spans[mid] = (base + m.start(), base + m.end())
    return spans


def apply(selector_text: str, p: Plan) -> str:
    """The selector with every model's tags set to the plan: written at the end
    of its element, or removed."""
    spans = _element_spans(selector_text)
    text = selector_text
    # Edit from the end so earlier spans stay valid.
    for mid, (start, end) in sorted(spans.items(), key=lambda kv: -kv[1][0]):
        element = text[start:end]
        cleaned = _TAG_ATTR_RE.sub("", element)
        tags = p.tags.get(mid)
        if tags is not None:
            # At the end of the element, just before "/>": the element's head
            # (id, name, prices), which other tools anchor on, stays unchanged.
            close = cleaned.rstrip().rfind("/>")
            cleaned = f"{cleaned[:close].rstrip()} {tags.attrs()}{cleaned[close:]}"
        if cleaned != element:
            text = text[:start] + cleaned + text[end:]
    return text


def base_tags(base_text: str) -> dict[str, Tags]:
    """The tags recorded in a committed selector."""
    options = _OPTIONS_RE.search(base_text)
    if not options:
        return {}
    out: dict[str, Tags] = {}
    for m in MODEL_RE.finditer(options.group(1)):
        attrs = _parse_attrs(m.group(1))
        mid, by, since = attrs.get("id"), attrs.get("superseded-by"), attrs.get("superseded-on")
        if mid and by and since:
            out[mid] = Tags(by, since, attrs.get("retired-on") or None)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the catalog's supersession rule.")
    parser.add_argument("--write", action="store_true", help="write the tags into the selector")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--base", type=Path, default=None, help="committed selector")
    args = parser.parse_args(argv)

    today = args.today or dt.datetime.now(dt.UTC).date()
    selector_text = SELECTOR_PATH.read_text()
    benchmarks = json.loads(BENCHMARKS_PATH.read_text()) if BENCHMARKS_PATH.exists() else {}
    base = base_tags(args.base.read_text()) if args.base else None
    p = plan(selector_text, benchmarks, today, base)

    names = {m.id: m.name for m in parse_models(selector_text, benchmarks)}
    for mid in p.newly:
        print(f"SUPERSEDED {names.get(mid, mid)} by {names.get(p.tags[mid].by, p.tags[mid].by)}")
    for mid in p.cleared:
        print(f"CLEARED {names.get(mid, mid)} (no longer superseded)")
    for mid in p.retired:
        t = p.tags[mid]
        print(
            f"RETIRED {names.get(mid, mid)} (superseded by {names.get(t.by, t.by)} since {t.since})"
        )

    if args.write:
        new_text = apply(selector_text, p)
        if new_text != selector_text:
            SELECTOR_PATH.write_text(new_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
