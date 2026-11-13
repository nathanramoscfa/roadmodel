#!/usr/bin/env python3
"""Add or decline every model the discovery lane flags, so none waits on a person.

The curation pass sees each flagged model first (the ``<provider_discovery>``
block) and may add or decline it with full context. What it leaves undecided is
disposed here, by rule, after the prose guard and before the rating guard:

ADD when the provider's own page prices the model AND the catalog carries a
same-series model the provider's own API offers, below it in version
(update/rating_guard.py ``predecessor``: the same name words, the highest
version below). The new ``<model>`` copies that predecessor's letters (the
rating guard's placeholder; update/derive_ratings.py measures them once
Artificial Analysis does) and jurisdiction, joins the provider's
``<provider>-api`` method, and takes its prices from the snapshot. best-for and
headline-benchmarks start empty: update/model_prose.py writes them.

ADD a priced model of a new series too: no same-series model the provider's
API offers is in the catalog. It starts from the rating guard's B placeholder
(S speed for a Mini/Flash/Haiku/Nano/Lite name), takes the provider's
jurisdiction from its snapshot and joins ``<provider>-api``. Until 2026-10 a
new series was declined here as NEW_SERIES while the curation pass, barred from
adding rows, left it to this script, so Gemini 4 Argon reached neither (#1120).

Both kinds merge by rule (2026-11): the new ``<model>`` is the template in
update/lifecycle_rules.py, which the refresh gate (update/automation_integrity.py)
rebuilds and admits. Until then each waited in the catalog's review PR for a
person, and Gemini 4 Carbon and Fable 5.2 sat there. Two rules guard what is
added:

- A SECOND SOURCE must name the model: a docs tracker (its committed snapshot
  or this run's read of the docs page) or a vendor's default-effort table
  (``SECOND_SOURCES``), besides the pricing page. Until one does, a provisional
  ONE_SOURCE line holds it, lifted the run one does.
- An ALIAS is declined, not added: Anthropic's pricing table lists "Claude
  Mythos N" for Fable N, so that row is declined as the page's other name for
  the carried model once Fable N is carried.

DECLINE everything else, with a line in docs/model-tier-cost-scale.md's
"Declined Models (discovery lane)" section:

- SPECIALIZED: an image, audio, video, embedding, robotics or computer-use
  model (by its name). The catalog rates general text models.
- NO_PRICE: the provider's page shows no price the extractor reads. Provisional:
  once the page prices it, update/discovery.py shows it to the curation pass
  again, and this script then adds it.

A standing NEW_SERIES line from before 2026-10 is re-decided: the model is
added and the line lifted.

Models a CLI's docs introduce (the Gemini and Claude Code trackers'
``unexpected_models``) are disposed the same way: a docs page lists no price.

One decision stands per model. The curation pass's own decline outranks a
NO_PRICE line, which then goes; so does a NO_PRICE line for a model the
catalog now carries.

    python update/dispose_discoveries.py --write    # apply and report
    python update/dispose_discoveries.py            # report only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derive_ratings  # noqa: E402
import rating_guard  # noqa: E402
from discovery import (  # noqa: E402
    DECLINED_HEADING,
    DECLINED_LINE_RE,
    NO_PRICE,
    Declined,
    _section,
    _variants,
    catalog_keys,
    normalize,
    parse_declined,
    snapshot_paths,
)
from lifecycle_rules import (  # noqa: E402
    NEW_SERIES,
    ONE_SOURCE,
    SPECIALIZED,
    alias_reason,
    money,
    pricing_note,
    valid_id,
    valid_name,
)
from lifecycle_rules import model_element as _rule_element  # noqa: E402
from merge_catalog import cost_tier_for_output_price  # noqa: E402
from selector_re import ATTR_RE, METHOD_RE, MODEL_RE  # noqa: E402

UPDATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"
REPORT_PATH = UPDATE_DIR / ".last-dispositions.md"

# The name words that mark a specialized model (the Google extractor keeps the
# same kinds off its flags; a docs page or another provider's list does not).
_SPECIALIZED_RE = re.compile(
    r"\b(image|imagen|veo|video|audio|tts|speech|transcribe|realtime|embedding|embed|"
    r"live|nano banana|robotics|computer[ -]use)\b",
    re.IGNORECASE,
)

# The trackers whose snapshots name models their CLI's docs introduced.
TRACKER_FLAGS: dict[str, Path] = {
    "google": UPDATE_DIR / "gemini-thinking.json",
    "anthropic": UPDATE_DIR / "claude-code-effort.json",
}
# Snapshots that name models a provider's docs or catalog list: a model a
# pricing page flags joins only once one of these names it too, so one misread
# page cannot add a model (update/default-efforts.json carries every vendor's
# default-effort table).
SECOND_SOURCES: tuple[Path, ...] = (
    UPDATE_DIR / "gemini-thinking.json",
    UPDATE_DIR / "claude-code-effort.json",
    UPDATE_DIR / "default-efforts.json",
    # This run's own reads of the two docs pages (update-models.yml), so a
    # tracker held back by its conformance gate still names its models: Gemini
    # 4 Hydrogen waited while Gemini's new `xhigh` level held the Gemini tracker.
    UPDATE_DIR / ".cache" / "gemini-thinking.json",
    UPDATE_DIR / ".cache" / "claude-code-effort.json",
)
# A provider page's other name for a model the catalog carries: Anthropic's
# pricing table lists "Claude Mythos 5.2" for Fable 5.2 (as it did for 5 and
# 5.1). (provider, normalized flag pattern, normalized carried name).
ALIASES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("anthropic", re.compile(r"(?:claude-)?mythos-(?P<v>\d+(?:-\d+)*)"), "fable-{v}"),
)
# Providers whose ids separate version digits with a dash ("claude-opus-5-5").
DASH_VERSIONS = frozenset({"anthropic"})
_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)


@dataclass(frozen=True)
class Flag:
    provider: str
    slug: str
    input_price: float | None
    output_price: float | None
    source: str  # "provider page" or "<tracker> docs"
    jurisdiction: str = "unknown"  # the provider snapshot's; a new series takes it

    @property
    def priced(self) -> bool:
        return self.input_price is not None and self.output_price is not None


@dataclass(frozen=True)
class Action:
    kind: str  # "added" | "declined" | "lifted"
    flag: Flag
    detail: str

    def line(self) -> str:
        return f"- {self.kind}: `{self.flag.provider}/{self.flag.slug}` — {self.detail}"


def _price(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def load_flags(snapshots: list[Path], tracker_flags: dict[str, Path]) -> list[Flag]:
    """Every model a provider snapshot or a tracker flags, priced where the
    snapshot read a price. A model both flag is listed once, priced."""
    flags: dict[tuple[str, str], Flag] = {}
    for path in snapshots:
        snap = json.loads(path.read_text())
        provider = str(snap.get("provider", path.stem.removeprefix("catalog-")))
        jurisdiction = str(snap.get("jurisdiction") or "unknown")
        prices = {
            str(r["slug"]): (
                _price(r.get("input_price_per_1m")),
                _price(r.get("output_price_per_1m")),
            )
            for r in snap.get("discovered") or []
            if isinstance(r, dict) and r.get("slug")
        }
        for slug in snap.get("unexpected_slugs") or []:
            in_p, out_p = prices.get(str(slug), (None, None))
            flags[(provider, normalize(str(slug)))] = Flag(
                provider, str(slug), in_p, out_p, "provider page", jurisdiction
            )
    for provider, path in tracker_flags.items():
        if not path.exists():
            continue
        for name in json.loads(path.read_text()).get("unexpected_models") or []:
            key = (provider, normalize(str(name)))
            if key not in flags:
                flags[key] = Flag(provider, str(name), None, None, f"{path.stem} docs")
    return sorted(flags.values(), key=lambda f: (f.provider, f.slug))


def _version_groups(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def new_id(flag: Flag, predecessor_id: str) -> str:
    """An API-id slug ("gpt-6.1-sol") is the id. A display name ("Claude Opus
    5.6") follows the predecessor's id, its version swapped in the provider's
    convention ("claude-opus-5-5" -> "claude-opus-5-6")."""
    if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", flag.slug):
        return flag.slug
    new_digits = _version_groups(flag.slug)
    old_digits = _version_groups(predecessor_id)
    sep = "-" if flag.provider in DASH_VERSIONS else "."
    old = re.search(r"\d+(?:[.\-]\d+)*", predecessor_id)
    if not old or not new_digits:
        return re.sub(r"[^a-z0-9.]+", "-", flag.slug.lower()).strip("-")
    tail = predecessor_id[old.end() :]
    # A versioned predecessor sets the separator ("claude-fable-5.1" ->
    # "claude-fable-5.2", "claude-opus-5-5" -> "claude-opus-5-6").
    if len(old_digits) > 1:
        sep = "-" if "-" in old.group(0) else "."
    return predecessor_id[: old.start()] + sep.join(new_digits) + tail


def series_id(flag: Flag) -> str:
    """A new series' id: an API-id slug as it is, a display name lower-cased
    with dashes ("Gemini 4 Argon" -> "gemini-4-argon"), versions keeping the
    provider's separator ("Gemini 3.9 Flash" -> "gemini-3.9-flash")."""
    if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", flag.slug):
        return flag.slug
    if flag.provider in DASH_VERSIONS:
        return normalize(flag.slug)
    return re.sub(r"[^a-z0-9.]+", "-", flag.slug.lower()).strip("-.")


def new_name(flag: Flag, predecessor_name: str) -> str:
    """The predecessor's display name with the new version: "GPT-6 Sol" ->
    "GPT-6.1 Sol", "Opus 5.5" -> "Opus 5.6"."""
    version = ".".join(_version_groups(flag.slug))
    if not version:
        return flag.slug
    return re.sub(r"\d+(?:\.\d+)*", version, predecessor_name, count=1)


_money = money


def model_element(
    model_id: str, name: str, flag: Flag, jurisdiction: str, tiers: dict[str, str]
) -> str:
    """The new ``<model>``, from the template the refresh gate rebuilds it with
    (update/lifecycle_rules.py)."""
    if flag.input_price is None or flag.output_price is None:
        raise ValueError(f"{flag.provider}/{flag.slug} has no price to add it at")
    if not (valid_id(model_id) and valid_name(name)):
        raise ValueError(
            f"{flag.provider}/{flag.slug}: {model_id!r} / {name!r} is not a model id and name"
        )
    return _rule_element(
        model_id,
        name,
        money(flag.input_price),
        money(flag.output_price),
        jurisdiction,
        tiers,
        pricing_note(flag.provider),
    )


def _strings(value: object) -> set[str]:
    """Every string in a JSON value, keys included."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        out: set[str] = set()
        for key, item in value.items():
            out |= {str(key)} | _strings(item)
        return out
    if isinstance(value, list):
        return set().union(*(_strings(item) for item in value)) if value else set()
    return set()


def second_source_names(paths: tuple[Path, ...] = SECOND_SOURCES) -> set[str]:
    """The model names the second sources list, normalized, maker prefix both
    ways ("Claude Fable 5.2" and "Fable 5.2" read alike)."""
    names: set[str] = set()
    for path in paths:
        if path.exists():
            for text in _strings(json.loads(path.read_text())):
                names |= _variants(text)
    return names


def alias_of(flag: Flag, selector: str) -> str | None:
    """The carried model a flag is another name for, if a rule says so."""
    for provider, pattern, target in ALIASES:
        if provider != flag.provider:
            continue
        m = pattern.fullmatch(normalize(flag.slug))
        if m is None:
            continue
        key = target.format(**m.groupdict())
        for mid, model in rating_guard.models(selector).items():
            if key in _variants(mid) | _variants(model.name):
                return mid
    return None


def _alias_pattern(flag: Flag) -> bool:
    return any(
        p == flag.provider and pattern.fullmatch(normalize(flag.slug)) for p, pattern, _ in ALIASES
    )


def _api_offered(selector: str, provider: str) -> set[str]:
    for m in METHOD_RE.finditer(selector):
        attrs = dict(ATTR_RE.findall(m.group(1)))
        if attrs.get("id") == f"{provider}-api":
            return {x.strip() for x in attrs.get("supports-models", "").split(",") if x.strip()}
    return set()


def add_model(selector: str, flag: Flag, predecessor_id: str | None) -> tuple[str, str]:
    """``selector`` with the flagged model added beside its predecessor (or at
    the end of its cost tier) and on the provider's API method. Without a
    predecessor it is a new series, with the rating guard's B placeholder.
    Returns the new text and the new id."""
    if predecessor_id is not None:
        pred = rating_guard.models(selector)[predecessor_id]
        model_id = new_id(flag, predecessor_id)
        name = new_name(flag, pred.name)
        jurisdiction = _pred_jurisdiction(selector, predecessor_id)
        tiers = pred.tiers
    else:
        model_id = series_id(flag)
        name = flag.slug
        jurisdiction = flag.jurisdiction
        tiers, _ = rating_guard.placeholder(
            rating_guard.Model(model_id, name, {}), rating_guard.models(selector)
        )
    element = model_element(model_id, name, flag, jurisdiction, tiers)
    if flag.output_price is None:
        raise ValueError(f"{flag.provider}/{flag.slug} has no price to add it at")
    tier = cost_tier_for_output_price(flag.output_price)
    block = _OPTIONS_RE.search(selector)
    if block is None:
        raise ValueError("<model-options> block not found")
    options = block.group(1)
    groups = list(re.finditer(r'<tier cost="([^"]+)">(.*?)</tier>', options, re.DOTALL))
    target = next((g for g in groups if g.group(1) == tier), None)
    if target is None:
        raise ValueError(f'<model-options> has no <tier cost="{tier}"> group')
    pred_el = next(
        (
            m
            for m in MODEL_RE.finditer(options)
            if dict(ATTR_RE.findall(m.group(1))).get("id") == predecessor_id
        ),
        None,
    )
    if pred_el is not None and target.start(2) <= pred_el.start() < target.end(2):
        at = pred_el.end()
    else:
        at = target.end(2)
        while at > target.start(2) and options[at - 1] in " \t":
            at -= 1
        if options[at - 1] == "\n":
            at -= 1
    new_options = options[:at] + "\n" + element + options[at:]
    selector = selector[: block.start(1)] + new_options + selector[block.end(1) :]
    return _join_api_method(selector, flag.provider, model_id), model_id


def _pred_jurisdiction(selector: str, model_id: str) -> str:
    for m in MODEL_RE.finditer(selector):
        attrs: dict[str, str] = dict(ATTR_RE.findall(m.group(1)))
        if attrs.get("id") == model_id:
            return attrs.get("jurisdiction", "unknown")
    return "unknown"


def _join_api_method(selector: str, provider: str, model_id: str) -> str:
    def edit(m: re.Match[str]) -> str:
        body: str = m.group(1)
        if f'id="{provider}-api"' not in body:
            return m.group(0)
        return m.group(0).replace(
            body,
            re.sub(
                r'supports-models="([^"]*)"',
                # The list's own separator: "a,b" stays comma-only.
                lambda s: (
                    f'supports-models="{s.group(1)}{", " if ", " in s.group(1) else ","}{model_id}"'
                    if s.group(1)
                    else f'supports-models="{model_id}"'
                ),
                body,
                count=1,
            ),
            1,
        )

    return METHOD_RE.sub(edit, selector)


def _write_declines(cost_scale: str, add: list[Declined], drop: set[Declined]) -> str:
    """The declined section with the lines in ``drop`` removed and ``add`` appended."""
    span = _section(cost_scale)
    trailing = "\n" if cost_scale.endswith("\n") else ""
    lines = cost_scale.splitlines()
    if span is None:
        lines += ["", DECLINED_HEADING, ""]
        span = (len(lines) - 2, len(lines))
    first, end = span

    def dropped(line: str) -> bool:
        m = DECLINED_LINE_RE.match(line.strip())
        if m is None:
            return False
        return Declined(m["provider"], m["slug"], m["reason"], m["date"]) in drop

    body = [line for line in lines[first + 1 : end] if not dropped(line)]
    while body and not body[-1].strip():
        body.pop()
    body += [d.line() for d in add]
    rest = lines[end:]
    return "\n".join(lines[: first + 1] + body + ([""] + rest if rest else [])) + trailing


def _listed(d: Declined) -> Flag:
    """A declined line as the flag the report names."""
    return Flag(d.provider, d.slug, None, None, "declined list")


def _standing(lines: list[Declined]) -> tuple[dict[tuple[str, str], Declined], set[Declined]]:
    """The decision that stands for each declined model, and the NO_PRICE lines
    another decision outranks: the curation pass's own line wins over this
    script's provisional one, and a model keeps one NO_PRICE line at most."""
    standing: dict[tuple[str, str], Declined] = {}
    outranked: set[Declined] = set()
    for d in lines:
        key = (d.provider, normalize(d.slug))
        held = standing.get(key)
        if held is None:
            standing[key] = d
        elif held.reason in (NO_PRICE, ONE_SOURCE):
            outranked.add(held)
            standing[key] = d
        elif d.reason in (NO_PRICE, ONE_SOURCE):
            outranked.add(d)
    return standing, outranked


def dispose(
    selector: str,
    cost_scale: str,
    flags: list[Flag],
    today: dt.date,
    second: set[str] | None = None,
) -> tuple[str, str, list[Action]]:
    """Return the selector and cost scale with every undecided flag disposed.
    ``second`` is the names a second source lists (``second_source_names``);
    None skips that rule."""
    actions: list[Action] = []
    declined, drop = _standing(parse_declined(cost_scale))
    for d in sorted(drop, key=lambda d: (d.provider, d.slug)):
        standing = declined[(d.provider, normalize(d.slug))]
        by_rule = standing.reason in (NO_PRICE, NEW_SERIES, SPECIALIZED, ONE_SOURCE)
        detail = (
            "a duplicate line" if by_rule else f"the curation pass declined it: {standing.reason}"
        )
        actions.append(Action("lifted", _listed(d), detail))
    new_declines: list[Declined] = []
    live = derive_ratings.live_ids(selector)
    # Another name for a model is decided after the model itself.
    for flag in sorted(flags, key=_alias_pattern):
        key = (flag.provider, normalize(flag.slug))
        prior = declined.get(key)
        if _variants(flag.slug) & catalog_keys(selector):
            continue  # carried: added by the pass or an earlier run
        if prior is not None and prior.reason not in (NO_PRICE, NEW_SERIES, ONE_SOURCE):
            continue  # the curation pass's decline, or a rule decline: it stands
        aliased = alias_of(flag, selector) if _alias_pattern(flag) else None
        if _alias_pattern(flag) and aliased is None:
            continue  # its model is not carried yet; decided once it is
        if aliased is not None:
            reason = alias_reason(aliased)
        elif _SPECIALIZED_RE.search(flag.slug):
            reason = SPECIALIZED
        elif flag.priced and second is not None and not (_variants(flag.slug) & second):
            reason = ONE_SOURCE
        else:
            offered = _api_offered(selector, flag.provider)
            pool = {
                mid: m
                for mid, m in rating_guard.models(selector).items()
                if mid in live and mid in offered
            }
            probe_id = (
                flag.slug
                if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", flag.slug)
                else normalize(flag.slug)
            )
            pred = rating_guard.predecessor(probe_id, pool)
            if flag.priced and pred is not None:
                selector, model_id = add_model(selector, flag, pred)
                if prior is not None:
                    drop.add(prior)
                    actions.append(Action("lifted", flag, "its price is on the provider page now"))
                actions.append(
                    Action(
                        "added",
                        flag,
                        f"as `{model_id}`, the `{pred}` successor at "
                        f"{_money(flag.input_price or 0)}/{_money(flag.output_price or 0)}, "
                        f"with `{pred}`'s letters until Artificial Analysis measures it",
                    )
                )
                continue
            if flag.priced:
                selector, model_id = add_model(selector, flag, None)
                if prior is not None:
                    drop.add(prior)
                    actions.append(Action("lifted", flag, "a new series is added now"))
                actions.append(
                    Action(
                        "added",
                        flag,
                        f"as `{model_id}`, a new series at "
                        f"{_money(flag.input_price or 0)}/{_money(flag.output_price or 0)}, "
                        "with the B placeholder letters until Artificial Analysis measures it",
                    )
                )
                continue
            reason = NO_PRICE
        if prior is not None and prior.reason == reason:
            continue
        if prior is not None:
            drop.add(prior)
        new_declines.append(Declined(flag.provider, flag.slug, reason, today.isoformat()))
        actions.append(Action("declined", flag, reason))
    # A provisional line goes once the catalog carries its model, flagged or
    # not: the extractors stop flagging a carried model.
    carried = catalog_keys(selector)
    for d in declined.values():
        if d.reason in (NO_PRICE, ONE_SOURCE) and d not in drop and _variants(d.slug) & carried:
            drop.add(d)
            actions.append(Action("lifted", _listed(d), "the catalog carries it now"))
    if new_declines or drop:
        cost_scale = _write_declines(cost_scale, new_declines, drop)
    return selector, cost_scale, actions


def prune_carried(snapshots: list[Path], selector: str) -> list[str]:
    """Drop from each provider snapshot's ``unexpected_slugs`` every model the
    catalog now carries, with its ``discovered`` price row (G1: every
    discovered row names a flagged slug): the curation pass or this run added
    it after the snapshot was taken. Runs after the provider-API sync has read
    the rows, and keeps the committed snapshot and the committed catalog in
    agreement within one refresh. Returns ``provider/slug`` for each one pruned."""
    carried = catalog_keys(selector)
    live = derive_ratings.live_ids(selector)
    ids = {
        key: mid
        for mid, model in rating_guard.models(selector).items()
        if mid in live
        for key in _variants(mid) | _variants(model.name)
    }
    pruned: list[str] = []
    for path in snapshots:
        snap = json.loads(path.read_text())
        flagged = snap.get("unexpected_slugs")
        if not isinstance(flagged, list):
            continue
        keep = [s for s in flagged if not (_variants(str(s)) & carried)]
        if len(keep) == len(flagged):
            continue
        provider = str(snap.get("provider", path.stem.removeprefix("catalog-")))
        gone = [s for s in flagged if s not in keep]
        pruned += [f"{provider}/{s}" for s in gone]
        snap["unexpected_slugs"] = keep
        rows = snap.get("discovered")
        if isinstance(rows, list):
            snap["discovered"] = [
                r for r in rows if not (isinstance(r, dict) and r.get("slug") in gone)
            ]
            _price_added(snap, rows, gone, ids)
        path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    return pruned


def _price_added(
    snap: dict[str, object], rows: list[object], gone: list[str], ids: dict[str, str]
) -> None:
    """Move a newly carried live model's price row into the snapshot's priced
    models: from the next run its reader maps it by name
    (update/discovery.py ``carried_ids``), and the committed snapshot and
    catalog agree within this one."""
    models, slug_to_id = snap.get("models"), snap.get("slug_to_id")
    if not isinstance(models, list):
        return
    have = {m.get("id") for m in models if isinstance(m, dict)}
    for row in rows:
        if not (isinstance(row, dict) and row.get("slug") in gone):
            continue
        slug = str(row["slug"])
        mid = next((ids[k] for k in sorted(_variants(slug)) if k in ids), None)
        in_p, out_p = _price(row.get("input_price_per_1m")), _price(row.get("output_price_per_1m"))
        if mid is None or mid in have or in_p is None or out_p is None:
            continue
        models.append(
            {
                "id": mid,
                "slug": slug,
                "name": slug,
                "input_price_per_1m": in_p,
                "output_price_per_1m": out_p,
                "cache_read_per_1m": None,
            }
        )
        have.add(mid)
        if isinstance(slug_to_id, dict):
            slug_to_id[slug] = mid


def render_report(actions: list[Action]) -> str:
    if not actions:
        return ""
    return "\n".join(["## Discovery lane", "", *(a.line() for a in actions)]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--write", action="store_true", help="apply to the selector and cost scale")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None)
    args = parser.parse_args()

    today = args.today or dt.datetime.now(dt.UTC).date()
    flags = load_flags(snapshot_paths(), TRACKER_FLAGS)
    selector, cost_scale, actions = dispose(
        SELECTOR_PATH.read_text(), COST_SCALE_PATH.read_text(), flags, today, second_source_names()
    )
    report = render_report(actions)
    print(report or "## Discovery lane\n\nNothing left undecided.")
    if args.write:
        SELECTOR_PATH.write_text(selector)
        COST_SCALE_PATH.write_text(cost_scale)
        REPORT_PATH.write_text(report)
        for item in prune_carried(snapshot_paths(), selector):
            print(f"unflagged {item}: the catalog carries it now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
