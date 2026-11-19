"""The catalog's lifecycle rule: supersession, then retirement, applied as data.

A model is SUPERSEDED when another model in ``<model-options>``:

* has the same maker (the provider of the first-party access method that
  offers it, ``validate_catalog_conformance._model_makers``);
* costs the same or less, on the blended price (3 x input + 1 x output) / 4;
* scores higher on the Artificial Analysis Intelligence Index. A newer model
  AA has not measured yet counts its estimate (``docs/index-estimates.json``)
  less half the estimate's band, the margin a pick ranks it by
  (``roadmodel.scoring.estimate_penalty``): Claude Fable 5.2 launched cheaper
  than Fable 5.1 on every surface and estimated well above it, yet 5.1 stayed
  for want of a measurement that could not come while AA's were frozen
  (2026-11-16). The older model still needs a figure of its own, and once AA
  measures the newer one, the measurement decides;
* is rated at least as high in each of the seven categories; and
* is offered by every access method that offers the model, so the newer model
  is always there to take its place; and
* is available: a model benched in ``infra/model-availability.json`` (its
  provider withdrew or restricted access) displaces nothing, so a series keeps
  a recommendable model while its newest is benched (Fable 5 spent months
  benched on export-control grounds).

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

A NEAR-MISS is a same-maker model that passes every test but coverage: some
access method offers the old model and does not list the new one, so the old
model stays. The run prints ``NEAR-MISS <old> -> <new>: missing on <methods>``
for each one whose old model has no successor yet. The catalog cron checks
each (method, model) pair against the method's own source, and a near-miss
that lasts three days opens an issue that closes itself once it resolves.

Usage: ``python update/supersede.py --write [--today YYYY-MM-DD] [--base PATH]``
(``--base``: the committed selector, to restore tags a regenerated file
dropped). Prints one line per change for the PR body.
``python update/supersede.py --near-misses [--selector PATH] [--persisted-since
OLD_SELECTOR]`` prints only the near-misses (those the older selector had too).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import derive_ratings  # noqa: E402
from build_catalog import (  # noqa: E402
    RETIRE_AFTER_DAYS,
    TASK_CATEGORIES,
    _parse_access_methods,
    _parse_attrs,
    _parse_price,
)
from selector_re import MODEL_RE  # noqa: E402
from stale_claims import maker_of  # noqa: E402
from validate_catalog_conformance import _model_makers  # noqa: E402

REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
BENCHMARKS_PATH = REPO_ROOT / "docs" / "benchmarks.json"
ESTIMATES_PATH = REPO_ROOT / "docs" / "index-estimates.json"
AVAILABILITY_PATH = REPO_ROOT / "infra" / "model-availability.json"
EFFORT_RATINGS_PATH = derive_ratings.EFFORT_RATINGS_PATH

RATING_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_CITED_AA_RE = re.compile(r"AA Intelligence Index\s+(\d+(?:\.\d+)?)")
_TAG_ATTR_RE = re.compile(r'\s+(?:superseded-by|superseded-on|retired-on)="[^"]*"')

AGGREGATOR_METHODS: Final[frozenset[str]] = frozenset({"cursor", "openrouter", "ollama"})

# Series parser mirrored verbatim from src/roadmodel/series.py (keep in sync).
_SIZE_RE: Final = re.compile(r"(?<![a-z0-9.])a?\d+(?:\.\d+)?[bmk](?![a-z0-9])")
_VENDOR_WORDS: Final[frozenset[str]] = frozenset({"claude"})


def _split(model_id: str) -> tuple[str, tuple[str, ...]]:
    text = model_id.lower()
    return _SIZE_RE.sub(" ", text), tuple(sorted(_SIZE_RE.findall(text)))


def series(model_id: str) -> frozenset[str]:
    """The id's name words, plus any size; empty when it has no name word."""
    rest, sizes = _split(model_id)
    words = frozenset(re.findall(r"[a-z]+", rest)) - _VENDOR_WORDS
    if not words:
        return frozenset()
    return words | frozenset(f"size:{s}" for s in sizes)


def version(model_id: str) -> tuple[int, ...]:
    """The id's version numbers, in order: ``gpt-6.1-sol`` → (6, 1)."""
    rest, _ = _split(model_id)
    return tuple(int(n) for n in re.findall(r"\d+", rest))


def is_newer(old: str, new: str) -> bool:
    """Whether ``new`` is a later version of ``old``'s series."""
    s = series(old)
    return bool(s) and s == series(new) and version(new) > version(old)


def _pad_version(model_id: str) -> tuple[int, ...]:
    return tuple(-n for n in (version(model_id) + (0, 0, 0, 0))[:4])


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
    # The estimate less half its band, for a model AA has not measured.
    aa_estimate: float | None = None

    @property
    def standing(self) -> float | None:
        """The figure this model challenges an older one with: its AA Index,
        else its discounted estimate."""
        return self.aa_index if self.aa_index is not None else self.aa_estimate


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


def load_estimates(path: Path | None = None) -> dict[str, Any]:
    """The committed AA Index estimates, or none when the file is absent."""
    path = path or ESTIMATES_PATH
    return json.loads(path.read_text()) if path.exists() else {}


def estimate_penalty(band: float) -> float:
    """Half the band, to a tenth: ``roadmodel.scoring.estimate_penalty``,
    restated here so the catalog cron needs no package import (a test holds
    the two equal)."""
    return round(float(band) / 2, 1)


def discounted_estimates(estimates: dict[str, Any] | None) -> dict[str, float]:
    """Each estimated model's index less half its band."""
    out: dict[str, float] = {}
    for mid, row in ((estimates or {}).get("models") or {}).items():
        if not isinstance(row, dict):
            continue
        index, band = row.get("index"), row.get("band")
        if isinstance(index, (int, float)) and isinstance(band, (int, float)):
            out[str(mid)] = round(float(index) - estimate_penalty(band), 1)
    return out


def parse_models(
    selector_text: str, benchmarks: dict[str, Any], estimates: dict[str, Any] | None = None
) -> list[Model]:
    estimated = discounted_estimates(estimates)
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
        aa_index = _aa_index(mid, attrs, benchmarks)
        out.append(
            Model(
                id=mid,
                name=attrs.get("name", mid),
                blended=blended_price(in_p, out_p),
                aa_index=aa_index,
                ratings={
                    c: RATING_RANK.get(attrs.get(f"tier-{c}", ""), 0) for c in TASK_CATEGORIES
                },
                since=attrs.get("superseded-on") or None,
                by=attrs.get("superseded-by") or None,
                retired=attrs.get("retired-on") or None,
                aa_estimate=estimated.get(mid) if aa_index is None else None,
            )
        )
    return out


def unavailable_ids(path: Path = AVAILABILITY_PATH) -> frozenset[str]:
    """The model ids benched in the committed availability list."""
    if not path.exists():
        return frozenset()
    raw = json.loads(path.read_text())
    entries = raw.get("unavailable", []) if isinstance(raw, dict) else []
    return frozenset(str(e.get("id") if isinstance(e, dict) else e) for e in entries if e)


def _makers(selector_text: str, models: list[Model]) -> dict[str, str]:
    """Each model's maker: first-party method provider, else its id prefix."""
    out = _model_makers(selector_text)
    for m in models:
        if m.id not in out:
            inferred = maker_of(m.id)
            if inferred is not None:
                out[m.id] = inferred
    return out


def _method_providers(selector_text: str) -> dict[str, str]:
    return {
        str(m["id"]): str(m["provider"])
        for m in _parse_access_methods(selector_text)
        if m.get("id") and m.get("provider")
    }


def delisted_by_provider(directory: Path = UPDATE_DIR) -> dict[str, set[str]]:
    """Model ids each maker's scraped catalog marks missing from its API."""
    out: dict[str, set[str]] = {}
    for p in sorted(directory.glob("catalog-*.json")):
        raw = json.loads(p.read_text())
        provider = raw.get("provider")
        missing = raw.get("missing_mapped_models") or []
        if provider and missing:
            out.setdefault(str(provider), set()).update(str(m) for m in missing if m)
    return out


def _offered(selector_text: str) -> dict[str, set[str]]:
    """Each model id -> the access methods whose supports-models list it."""
    offered: dict[str, set[str]] = {}
    for method in _parse_access_methods(selector_text):
        for mid in method.get("supports_models", []):
            offered.setdefault(str(mid), set()).add(str(method.get("id", "")))
    return offered


def _required_methods(
    mid: str,
    offered: dict[str, set[str]],
    method_providers: dict[str, str],
    delisted: dict[str, set[str]],
) -> set[str]:
    """Access methods a successor must cover: ignore aggregators when first-party
    methods exist, and exclude provider-delisted channels."""
    where = offered.get(mid, set())
    first_party = where - AGGREGATOR_METHODS
    req = first_party if first_party else where
    return {m for m in req if mid not in delisted.get(method_providers.get(m, ""), ())}


def _beats(old: Model, new: Model, makers: dict[str, str], unavailable: frozenset[str]) -> bool:
    """Every supersession test but coverage: same maker, available, higher
    AA Index (an unmeasured newcomer's discounted estimate), plus for cross-series
    replacements no dearer blended price and ratings at least as high everywhere."""
    maker = makers.get(old.id)
    if maker is None or old.aa_index is None:
        return False
    standing = new.standing
    if new.id == old.id or standing is None or makers.get(new.id) != maker:
        return False
    if new.id in unavailable:
        return False
    if is_newer(old.id, new.id):
        return standing > old.aa_index
    if not (new.blended <= old.blended and standing > old.aa_index):
        return False
    return all(new.ratings[c] >= old.ratings[c] for c in TASK_CATEGORIES)


def successors(
    selector_text: str,
    models: list[Model],
    unavailable: frozenset[str] = frozenset(),
    delisted: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """Each superseded model's id -> the active head of its superseding line.
    A benched model is no successor."""
    makers = _makers(selector_text, models)
    offered = _offered(selector_text)
    method_providers = _method_providers(selector_text)
    if delisted is None:
        delisted = delisted_by_provider()
    out: dict[str, str] = {}
    for old in models:
        req = _required_methods(old.id, offered, method_providers, delisted)
        best: Model | None = None
        for new in models:
            if not _beats(old, new, makers, unavailable):
                continue
            if not req <= offered.get(new.id, set()):
                continue
            cand_key = (-new.standing, _pad_version(new.id), new.blended, new.id)  # type: ignore[operator]
            best_key = (
                (-best.standing, _pad_version(best.id), best.blended, best.id)  # type: ignore[operator]
                if best is not None
                else None
            )
            if best_key is None or cand_key < best_key:
                best = new
        if best is not None:
            out[old.id] = best.id
    # Resolve transitively so multi-hop supersession points directly at the active head.
    for mid in list(out):
        seen = {mid}
        cur = out[mid]
        while cur in out and out[cur] not in seen:
            seen.add(cur)
            cur = out[cur]
        out[mid] = cur
    return out


@dataclass(frozen=True)
class NearMiss:
    """A same-maker model that passes every test against ``old``
    except coverage: the access methods in ``missing`` offer ``old`` and do
    not list ``new``, so ``old`` stays in the catalog."""

    old: str
    new: str
    missing: tuple[str, ...]

    def line(self) -> str:
        return f"NEAR-MISS {self.old} -> {self.new}: missing on {', '.join(self.missing)}"


_NEAR_MISS_RE = re.compile(r"^NEAR-MISS (?P<old>\S+) -> (?P<new>\S+): missing on (?P<missing>.+)$")


def near_misses(
    selector_text: str,
    models: list[Model],
    unavailable: frozenset[str] = frozenset(),
    delisted: dict[str, set[str]] | None = None,
) -> list[NearMiss]:
    """Every near-miss among ``models`` whose old model has no successor yet
    (a model already superseded has nothing to wait for)."""
    makers = _makers(selector_text, models)
    offered = _offered(selector_text)
    method_providers = _method_providers(selector_text)
    if delisted is None:
        delisted = delisted_by_provider()
    superseded = successors(selector_text, models, unavailable, delisted)
    out: list[NearMiss] = []
    for old in models:
        if old.id in superseded:
            continue
        req = _required_methods(old.id, offered, method_providers, delisted)
        for new in models:
            if not _beats(old, new, makers, unavailable):
                continue
            missing = req - offered.get(new.id, set())
            if missing:
                out.append(NearMiss(old.id, new.id, tuple(sorted(missing))))
    return out


def parse_near_miss(line: str) -> NearMiss | None:
    """A ``NEAR-MISS`` line back into its parts, or None."""
    m = _NEAR_MISS_RE.match(line.strip())
    if m is None:
        return None
    return NearMiss(m["old"], m["new"], tuple(x.strip() for x in m["missing"].split(",")))


def live_near_misses(
    selector_text: str, benchmarks: dict[str, Any], estimates: dict[str, Any] | None = None
) -> list[NearMiss]:
    """The near-misses among the selector's unretired models. ``estimates``
    defaults to the committed ones, so every caller (the catalog pass's
    targeted checks in update_models.py, close_resolved_issues.py) judges
    a pair as the rule does."""
    if estimates is None:
        estimates = load_estimates()
    live = [m for m in parse_models(selector_text, benchmarks, estimates) if not m.retired]
    return near_misses(selector_text, live, unavailable_ids())


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
    unavailable: frozenset[str] = frozenset(),
    estimates: dict[str, Any] | None = None,
    delisted: dict[str, set[str]] | None = None,
) -> Plan:
    """What each model's tags should be after this run. ``base`` holds the tags
    of the committed selector, so a tag a regenerated file dropped comes back
    with its original dates."""
    models = parse_models(selector_text, benchmarks, estimates)
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
    if delisted is None:
        delisted = delisted_by_provider()
    delisted_ids = {mid for ids in delisted.values() for mid in ids}
    makers = _makers(selector_text, live)
    succ = successors(selector_text, live, unavailable, delisted)
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
        newer_versions = sum(
            1
            for c in live
            if c.id != m.id and makers.get(c.id) == makers.get(m.id) and is_newer(m.id, c.id)
        )
        retire_now = (
            (today - dt.date.fromisoformat(first_seen)).days >= RETIRE_AFTER_DAYS
            or m.id in delisted_ids
            or newer_versions >= 2
        )
        if retire_now:
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


def rederive(
    selector_text: str, benchmarks: dict[str, Any]
) -> tuple[str, list[dict[str, Any]], str]:
    """(selector, changes, effort-ratings document) after a retirement: what
    ``derive_ratings.py --write`` makes of the selector, built from its own
    steps so that file stays the one the catalog baseline pins."""
    changes, _ = derive_ratings.plan_changes(selector_text, benchmarks)
    text = derive_ratings.apply_changes(selector_text, changes)
    text = derive_ratings.regenerate_coding_enumeration(text)
    text = derive_ratings.regenerate_multimodal_enumeration(text)
    effort = derive_ratings.render_effort_ratings(derive_ratings.effort_letters(text, benchmarks))
    return text, changes, effort


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
    parser.add_argument(
        "--near-misses",
        action="store_true",
        help="print only the NEAR-MISS lines, and write nothing",
    )
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH, help="the selector to read")
    parser.add_argument(
        "--persisted-since",
        type=Path,
        default=None,
        help="with --near-misses: an older selector; print only the near-misses it had too",
    )
    args = parser.parse_args(argv)

    today = args.today or dt.datetime.now(dt.UTC).date()
    selector_text = args.selector.read_text()
    benchmarks = json.loads(BENCHMARKS_PATH.read_text()) if BENCHMARKS_PATH.exists() else {}
    estimates = load_estimates()
    if args.near_misses:
        found = live_near_misses(selector_text, benchmarks, estimates)
        if args.persisted_since is not None:
            then = {
                (n.old, n.new)
                for n in live_near_misses(args.persisted_since.read_text(), benchmarks, estimates)
            }
            found = [n for n in found if (n.old, n.new) in then]
        for n in found:
            print(n.line())
        return 0
    base = base_tags(args.base.read_text()) if args.base else None
    p = plan(selector_text, benchmarks, today, base, unavailable_ids(), estimates)

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
    for n in live_near_misses(selector_text, benchmarks, estimates):
        print(n.line())

    if args.write:
        new_text = apply(selector_text, p)
        if p.retired:
            # Ranks are taken over the live models, so a retirement narrows the
            # field and moves other models' letters: re-derive them in the same
            # write, or derive_ratings.py --check fails on the retirement day.
            new_text, changes, effort = rederive(new_text, benchmarks.get("models", {}))
            for ch in changes:
                print(
                    f"RERATED {names.get(ch['id'], ch['id'])}: {ch['category']} "
                    f"{ch['from']} → {ch['to']} (the retirements narrowed the field)"
                )
            if not EFFORT_RATINGS_PATH.exists() or EFFORT_RATINGS_PATH.read_text() != effort:
                EFFORT_RATINGS_PATH.write_text(effort)
        if new_text != selector_text:
            args.selector.write_text(new_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
