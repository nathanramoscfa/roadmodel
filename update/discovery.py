"""The provider-page discovery lane, as data the catalog cron can act on.

Every provider-direct snapshot (``update/catalog-<provider>.json``) names, in
``unexpected_slugs``, the models its provider prices that the catalog neither
carries nor declines; where the extractor could read them, ``discovered``
carries each one's price too. ``update/prompt.md`` tells the curation model to
add or decline every such model, but until this module the model was never
shown the snapshots: ``update_models.build_user_message`` sent the two docs,
the Cursor page and the benchmark sources, nothing else. That is how
``gpt-6-astra`` sat flagged, and never added, for three weeks.

A flagged model leaves the lane one of two ways:

* the catalog adds it (its id or name then matches a ``<model>`` element in
  ``<model-options>``), or
* the curation model declines it with a line in the
  ``## Declined Models (discovery lane)`` section of
  ``docs/model-tier-cost-scale.md``::

      - <provider>/<slug> — <reason> (declined YYYY-MM-DD)

The curation model regenerates that file whole on every run, so
``--preserve-declined`` restores any line it dropped from the committed copy.
``--check`` prints the flagged models still neither added nor declined, one
``provider/slug`` per line, for the cron's issue step.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UPDATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"

DECLINED_HEADING = "## Declined Models (discovery lane)"
DECLINED_LINE_RE = re.compile(
    r"^- (?P<provider>[a-z0-9.-]+)/(?P<slug>\S(?:.*?\S)?) — (?P<reason>.+?) "
    r"\(declined (?P<date>\d{4}-\d{2}-\d{2})\)\s*$"
)
_MODEL_TAG_RE = re.compile(r"<model\s+[^>]*?\bid=\"([^\"]+)\"[^>]*?\bname=\"([^\"]+)\"", re.S)
# A maker prefix a provider's page puts on a name the catalog drops ("Claude
# Mythos 5" is catalogued as "Mythos 5" or "claude-mythos-5").
_MAKER_PREFIXES = ("claude-", "anthropic-", "openai-", "google-", "xai-")


def normalize(name: str) -> str:
    """Compare model names and ids on one spelling: lower case, every run of
    other characters a single dash. ``claude-opus-5-5``, ``Claude Opus 5.5``
    and ``claude opus 5.5`` all read ``claude-opus-5-5``."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _variants(name: str) -> set[str]:
    norm = normalize(name)
    out = {norm}
    for prefix in _MAKER_PREFIXES:
        if norm.startswith(prefix):
            out.add(norm[len(prefix) :])
    return out


def catalog_keys(selector_text: str) -> set[str]:
    """Every ``<model>`` id and name in the selector, normalized."""
    keys: set[str] = set()
    for mid, name in _MODEL_TAG_RE.findall(selector_text):
        keys.add(normalize(mid))
        keys.add(normalize(name))
    return keys


@dataclass(frozen=True)
class Declined:
    provider: str
    slug: str
    reason: str
    date: str

    def line(self) -> str:
        return f"- {self.provider}/{self.slug} — {self.reason} (declined {self.date})"


def parse_declined(cost_scale_text: str) -> list[Declined]:
    """The lines of the declined section, in order. Lines that do not match
    the format are ignored rather than guessed at."""
    out: list[Declined] = []
    in_section = False
    for line in cost_scale_text.splitlines():
        if line.startswith("## "):
            in_section = line.strip() == DECLINED_HEADING
            continue
        if not in_section:
            continue
        m = DECLINED_LINE_RE.match(line.strip())
        if m:
            out.append(Declined(m["provider"], m["slug"], m["reason"], m["date"]))
    return out


@dataclass(frozen=True)
class Discovery:
    provider: str
    slug: str
    source_url: str
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None

    def line(self) -> str:
        if self.input_price_per_1m is not None and self.output_price_per_1m is not None:
            price = (
                f"${self.input_price_per_1m:g} input / ${self.output_price_per_1m:g} output "
                "per 1M tokens (provider page)"
            )
        else:
            price = "price: read it from the provider page"
        return f"- {self.provider}/{self.slug} — {price} — source: {self.source_url}"


def snapshot_paths(update_dir: Path = UPDATE_DIR) -> list[Path]:
    return sorted(update_dir.glob("catalog-*.json"))


def _price(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def load(snapshots: list[Path], selector_text: str, cost_scale_text: str) -> list[Discovery]:
    """Every flagged model that the catalog neither carries nor declines, in
    provider then slug order, with its price where the snapshot recorded one."""
    carried = catalog_keys(selector_text)
    declined = {(d.provider, normalize(d.slug)) for d in parse_declined(cost_scale_text)}
    found: list[Discovery] = []
    for path in snapshots:
        snap = json.loads(path.read_text())
        provider = str(snap.get("provider", path.stem.removeprefix("catalog-")))
        source_url = str(snap.get("source_url", ""))
        prices: dict[str, tuple[float | None, float | None]] = {}
        for row in snap.get("discovered") or []:
            if isinstance(row, dict) and row.get("slug"):
                prices[str(row["slug"])] = (
                    _price(row.get("input_price_per_1m")),
                    _price(row.get("output_price_per_1m")),
                )
        for slug in snap.get("unexpected_slugs") or []:
            slug = str(slug)
            if _variants(slug) & carried:
                continue
            if (provider, normalize(slug)) in declined:
                continue
            in_p, out_p = prices.get(slug, (None, None))
            found.append(Discovery(provider, slug, source_url, in_p, out_p))
    return sorted(found, key=lambda d: (d.provider, d.slug))


def render_block(discoveries: list[Discovery]) -> str:
    """The ``<provider_discovery>`` block for the curation model, or "" when
    there is nothing to add or decline."""
    if not discoveries:
        return ""
    lines = [
        "<provider_discovery>",
        "Models a provider's OWN pricing page prices that this catalog neither carries "
        "nor declines. ADD or DECLINE every entry, as the provider-snapshot discovery "
        "lane in your instructions describes.",
        *(d.line() for d in discoveries),
        "</provider_discovery>",
    ]
    return "\n".join(lines)


def _section(text: str) -> tuple[int, int] | None:
    """(first, end) line indices of the declined section, heading included, or
    None when the text has no such section."""
    lines = text.splitlines()
    try:
        first = next(i for i, line in enumerate(lines) if line.strip() == DECLINED_HEADING)
    except StopIteration:
        return None
    end = next((i for i in range(first + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return first, end


def preserve_declined(base_text: str, new_text: str) -> tuple[str, list[Declined]]:
    """``new_text`` with the declined section the regeneration dropped put back:
    the whole section, heading and introduction included, when it vanished; any
    declined line it lost, otherwise. Returns the text and the lines restored."""
    base_span = _section(base_text)
    if base_span is None:
        return new_text, []
    trailing = "\n" if new_text.endswith("\n") else ""
    new_span = _section(new_text)
    if new_span is None:
        first, end = base_span
        section = "\n".join(base_text.splitlines()[first:end]).rstrip()
        return new_text.rstrip("\n") + "\n\n" + section + "\n", parse_declined(base_text)
    kept = {(d.provider, normalize(d.slug)) for d in parse_declined(new_text)}
    missing = [d for d in parse_declined(base_text) if (d.provider, normalize(d.slug)) not in kept]
    if not missing:
        return new_text, []
    lines = new_text.splitlines()
    first, end = new_span
    insert_at = end
    while insert_at > first + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [d.line() for d in missing]
    return "\n".join(lines) + trailing, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The provider-page discovery lane: check, render, or preserve declines."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="print each flagged model still neither added nor declined (provider/slug)",
    )
    mode.add_argument("--block", action="store_true", help="print the <provider_discovery> block")
    mode.add_argument(
        "--preserve-declined",
        type=Path,
        metavar="BASE",
        help="restore declined lines the regenerated cost-scale dropped from BASE",
    )
    args = parser.parse_args(argv)

    if args.preserve_declined is not None:
        new_text, restored = preserve_declined(
            args.preserve_declined.read_text(), COST_SCALE_PATH.read_text()
        )
        if restored:
            COST_SCALE_PATH.write_text(new_text)
            for line in restored:
                print(f"discovery: restored declined line {line.provider}/{line.slug}")
        return 0

    found = load(snapshot_paths(), SELECTOR_PATH.read_text(), COST_SCALE_PATH.read_text())
    if args.block:
        print(render_block(found))
    else:
        for item in found:
            print(f"{item.provider}/{item.slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
