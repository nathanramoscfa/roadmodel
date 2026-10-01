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

DECLINE everything else, with a line in docs/model-tier-cost-scale.md's
"Declined Models (discovery lane)" section:

- NO_PRICE: the provider's page shows no price the extractor reads. Re-checked
  every run: once a price and a predecessor exist, the line is lifted and the
  model added.
- NEW_SERIES: no same-series model the provider's API offers is in the
  catalog. A new family enters through the curation pass, which sees it first.

Models a CLI's docs introduce (the Gemini and Claude Code trackers'
``unexpected_models``) are disposed the same way: a docs page lists no price.

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
    Declined,
    _section,
    _variants,
    catalog_keys,
    normalize,
    parse_declined,
    snapshot_paths,
)
from merge_catalog import cost_tier_for_output_price  # noqa: E402
from selector_re import ATTR_RE, METHOD_RE, MODEL_RE  # noqa: E402

UPDATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"
REPORT_PATH = UPDATE_DIR / ".last-dispositions.md"

NO_PRICE = "no price on the provider page; re-checked each run"
NEW_SERIES = "a new series with no model from this provider in the catalog; a new family enters through the curation pass"

# The trackers whose snapshots name models their CLI's docs introduced.
TRACKER_FLAGS: dict[str, Path] = {
    "google": UPDATE_DIR / "gemini-thinking.json",
    "anthropic": UPDATE_DIR / "claude-code-effort.json",
}
PROVIDER_LABEL: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "zai": "z.ai",
    "groq": "Groq",
}
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
                provider, str(slug), in_p, out_p, "provider page"
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
    if len(old_digits) > 1 and "-" in old.group(0):
        sep = "-"
    return predecessor_id[: old.start()] + sep.join(new_digits) + tail


def new_name(flag: Flag, predecessor_name: str) -> str:
    """The predecessor's display name with the new version: "GPT-6 Sol" ->
    "GPT-6.1 Sol", "Opus 5.5" -> "Opus 5.6"."""
    version = ".".join(_version_groups(flag.slug))
    if not version:
        return flag.slug
    return re.sub(r"\d+(?:\.\d+)*", version, predecessor_name, count=1)


def _money(value: float) -> str:
    return f"${value:.2f}"


def model_element(
    model_id: str, name: str, flag: Flag, jurisdiction: str, tiers: dict[str, str]
) -> str:
    label = PROVIDER_LABEL.get(flag.provider, flag.provider)
    t = {c: tiers.get(c, "B") for c in rating_guard.CATEGORIES}
    if flag.input_price is None or flag.output_price is None:
        raise ValueError(f"{flag.provider}/{flag.slug} has no price to add it at")
    return (
        f'      <model id="{model_id}" name="{name}"\n'
        f'             input-price-per-1m="{_money(flag.input_price)}" output-price-per-1m="{_money(flag.output_price)}"\n'
        f'             jurisdiction="{jurisdiction}"\n'
        f'             tier-coding="{t["coding"]}" tier-planning="{t["planning"]}" tier-agentic="{t["agentic"]}"\n'
        f'             tier-multimodal="{t["multimodal"]}" tier-long-context="{t["long-context"]}" tier-knowledge="{t["knowledge"]}"\n'
        f'             tier-speed="{t["speed"]}"\n'
        f'             headline-benchmarks=""\n'
        f'             pricing-notes="Provider-direct {label} API per-token pricing (not via the Cursor pool)"\n'
        f'             best-for="" />'
    )


def _api_offered(selector: str, provider: str) -> set[str]:
    for m in METHOD_RE.finditer(selector):
        attrs = dict(ATTR_RE.findall(m.group(1)))
        if attrs.get("id") == f"{provider}-api":
            return {x.strip() for x in attrs.get("supports-models", "").split(",") if x.strip()}
    return set()


def add_model(selector: str, flag: Flag, predecessor_id: str) -> tuple[str, str]:
    """``selector`` with the flagged model added beside its predecessor (or at
    the end of its cost tier) and on the provider's API method. Returns the new
    text and the new id."""
    pred = rating_guard.models(selector)[predecessor_id]
    model_id = new_id(flag, predecessor_id)
    element = model_element(
        model_id,
        new_name(flag, pred.name),
        flag,
        _pred_jurisdiction(selector, predecessor_id),
        pred.tiers,
    )
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


def _write_declines(cost_scale: str, add: list[Declined], drop: set[tuple[str, str]]) -> str:
    """The declined section with lines in ``drop`` removed and ``add`` appended."""
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
        return (m["provider"], normalize(m["slug"])) in drop

    body = [line for line in lines[first + 1 : end] if not dropped(line)]
    while body and not body[-1].strip():
        body.pop()
    body += [d.line() for d in add]
    rest = lines[end:]
    return "\n".join(lines[: first + 1] + body + ([""] + rest if rest else [])) + trailing


def dispose(
    selector: str, cost_scale: str, flags: list[Flag], today: dt.date
) -> tuple[str, str, list[Action]]:
    """Return the selector and cost scale with every undecided flag disposed."""
    actions: list[Action] = []
    declined = {(d.provider, normalize(d.slug)): d for d in parse_declined(cost_scale)}
    new_declines: list[Declined] = []
    drop: set[tuple[str, str]] = set()
    live = derive_ratings.live_ids(selector)
    for flag in flags:
        if _variants(flag.slug) & catalog_keys(selector):
            continue  # carried: added by the pass or an earlier run
        key = (flag.provider, normalize(flag.slug))
        prior = declined.get(key)
        if prior is not None and prior.reason not in (NO_PRICE,):
            continue  # declined by the curation pass, or a new series: it stands
        offered = _api_offered(selector, flag.provider)
        pool = {
            mid: m
            for mid, m in rating_guard.models(selector).items()
            if mid in live and mid in offered
        }
        probe_id = (
            flag.slug if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", flag.slug) else normalize(flag.slug)
        )
        pred = rating_guard.predecessor(probe_id, pool)
        if flag.priced and pred is not None:
            selector, model_id = add_model(selector, flag, pred)
            if prior is not None:
                drop.add(key)
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
        reason = NO_PRICE if not flag.priced else NEW_SERIES
        if prior is not None and prior.reason == reason:
            continue
        if prior is not None:
            drop.add(key)
        new_declines.append(Declined(flag.provider, flag.slug, reason, today.isoformat()))
        actions.append(Action("declined", flag, reason))
    if new_declines or drop:
        cost_scale = _write_declines(cost_scale, new_declines, drop)
    return selector, cost_scale, actions


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
        SELECTOR_PATH.read_text(), COST_SCALE_PATH.read_text(), flags, today
    )
    report = render_report(actions)
    print(report or "## Discovery lane\n\nNothing left undecided.")
    if args.write:
        SELECTOR_PATH.write_text(selector)
        COST_SCALE_PATH.write_text(cost_scale)
        REPORT_PATH.write_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
