"""Deterministically extract Anthropic's catalog (pricing) facts from the official
Anthropic pricing docs.

Phase 4.6 T3 — the first MIGRATION of a Cursor-overlapping provider to a
provider-direct catalog source. Anthropic publishes a clean Markdown pricing
table at ``platform.claude.com/docs/.../pricing.md`` (the analog of
code.claude.com's ``model-config.md``), so — unlike the HTML DeepSeek source —
this is a Markdown-table parse, no bs4.

This source makes **Anthropic's own page authoritative** for Claude prices: the
price-provenance check in ``update/validate_catalog_conformance.py`` asserts the
selector's Anthropic prices EQUAL this snapshot, so Cursor's pricing-page mirror
can no longer be the authority — a Cursor↔Anthropic divergence fails CI. Pricing
facts only; tier ratings + benchmarks remain the catalog cron's benchmark-driven
(Cursor-maintained) lane.

Only the models the selector actually recommends are mapped (``NAME_TO_ID``);
Anthropic lists many more (Mythos, Opus 4.6/4.5, deprecated/retired) that are
deliberately NOT in ``<model-options>``.

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (the docs were
restructured so the deterministic parse no longer finds what it expects).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-anthropic.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-anthropic.json"

DOCS_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
PROVIDER = "anthropic"
JURISDICTION = "us"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Anthropic pricing-table display name -> canonical selector id. ONLY the models
# the selector recommends are mapped; the page lists many more that are
# deliberately not in <model-options>.
NAME_TO_ID = {
    "Claude Fable 5": "claude-fable-5",
    "Claude Opus 4.8": "opus-4.8",
    "Claude Opus 4.7": "opus-4.7",
    "Claude Sonnet 5": "claude-sonnet-5",
    "Claude Sonnet 4.6": "sonnet-4.6",
    "Claude Haiku 4.5": "claude-4.5-haiku",
}

# Literal substrings that MUST survive in the Markdown. Their absence means a
# restructure -> fail loud rather than emit a partial/empty snapshot.
REQUIRED_ANCHORS = (
    "Base Input Tokens",
    "Output Tokens",
    "Claude Opus 4.8",
    "Claude Sonnet 4.6",
    "/ MTok",
)

_DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")


class ExtractError(RuntimeError):
    """The pricing docs no longer match the structure this parser expects."""


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def verify_anchors(md: str) -> None:
    missing = [a for a in REQUIRED_ANCHORS if a not in md]
    if missing:
        raise ExtractError(f"expected pricing anchors missing (restructure?): {missing}")


def _dollars(cell: str) -> float | None:
    m = _DOLLAR_RE.search(cell)
    return float(m.group(1)) if m else None


# Anthropic time-boxes introductory pricing by splitting a model across TWO rows
# and labelling the period IN THE NAME CELL, e.g.
#   "Claude Sonnet 5 [through August 31, 2026](…#claude-sonnet-5-introductory-pricing)"
#   "Claude Sonnet 5 starting September 1, 2026"
# A plain NAME_TO_ID lookup misses both (the label is part of the cell), which is
# why Sonnet 5 was silently absent from this snapshot — and therefore from the
# catalog — even though it is Claude Code's default model. Strip the label to get
# the base name, then keep only the row in effect TODAY so the snapshot always
# carries the price actually being charged, and rolls over on its own.
_THROUGH_RE = re.compile(r"^(?P<base>.*?)\s*\[through\s+(?P<date>[^\]]+)\]\([^)]*\)\s*$")
_STARTING_RE = re.compile(r"^(?P<base>.*?)\s+starting\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s*\d{4})\s*$")


def _parse_period_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def _split_period(cell: str) -> tuple[str, str | None, date | None]:
    """Split a pricing-row name cell into (base_name, kind, boundary_date)."""
    for kind, pattern in (("through", _THROUGH_RE), ("starting", _STARTING_RE)):
        m = pattern.match(cell)
        if m:
            return m.group("base").strip(), kind, _parse_period_date(m.group("date"))
    return cell.strip(), None, None


def _is_effective(kind: str | None, boundary: date | None, today: date) -> bool:
    if kind is None or boundary is None:
        return True
    if kind == "through":
        return today <= boundary
    return today >= boundary


def _col(header: list[str], *needles: str) -> int | None:
    for i, h in enumerate(header):
        if all(n.lower() in h.lower() for n in needles):
            return i
    return None


def parse_pricing_table(md: str, *, today: date | None = None) -> list[dict[str, object]]:
    """Parse the standard per-token pricing table (header ``Base Input Tokens`` …
    ``Output Tokens``) and return per-model canonical pricing facts for the mapped
    models. The fast-mode / batch tables (which lack a ``Base Input Tokens``
    header) are ignored.

    ``today`` selects between time-boxed price rows (introductory vs standard);
    it is injectable so the choice is testable rather than clock-dependent.
    """
    today = today or date.today()
    header: list[str] | None = None
    data: list[list[str]] = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if header is not None:
                break  # the table ended at the first non-row line
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            if "Base Input Tokens" in cells and "Output Tokens" in cells:
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):  # the |---|---| separator
            continue
        data.append(cells)

    if header is None:
        raise ExtractError(
            "standard Anthropic pricing table not found (no 'Base Input Tokens' header)"
        )
    in_col = _col(header, "Input")
    out_col = _col(header, "Output")
    # The cache-READ column is "Cache Hits & Refreshes" — NOT the "… Cache Writes"
    # columns (which would be the first cells containing "Cache").
    cache_col = _col(header, "Hits")
    if cache_col is None:
        cache_col = _col(header, "Read")
    if in_col is None or out_col is None:
        raise ExtractError("pricing table missing an Input or Output column")

    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in data:
        if not row:
            continue
        name, period_kind, boundary = _split_period(row[0].strip())
        mid = NAME_TO_ID.get(name)
        if mid is None or mid in seen:
            continue
        if period_kind is not None and boundary is None:
            raise ExtractError(
                f"could not parse the effective date in pricing row {row[0].strip()!r}"
            )
        if not _is_effective(period_kind, boundary, today):
            continue  # a time-boxed price that is not the one being charged today
        in_price = _dollars(row[in_col]) if in_col < len(row) else None
        out_price = _dollars(row[out_col]) if out_col < len(row) else None
        if in_price is None or out_price is None:
            raise ExtractError(f"could not parse input/output price for {name!r}")
        seen.add(mid)
        models.append(
            {
                "id": mid,
                "slug": name,
                "name": name,
                "input_price_per_1m": in_price,
                "output_price_per_1m": out_price,
                "cache_read_per_1m": (
                    _dollars(row[cache_col])
                    if cache_col is not None and cache_col < len(row)
                    else None
                ),
            }
        )
    if not models:
        raise ExtractError("no mapped Anthropic models found in the pricing table")
    return models


def canonical_facts(models: list[dict[str, object]]) -> str:
    return json.dumps(
        {"provider": PROVIDER, "jurisdiction": JURISDICTION, "models": models},
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(md: str, *, source_url: str, today: date | None = None) -> dict[str, object]:
    verify_anchors(md)
    models = parse_pricing_table(md, today=today)

    found = {str(m["id"]) for m in models}
    missing = sorted(set(NAME_TO_ID.values()) - found)
    if missing:
        print(
            f"extract_anthropic_catalog: NOTE mapped selector model(s) not found on the "
            f"pricing page (deprecated / renamed?): {missing}. Their price stays "
            f"Cursor-sourced (not price-gated) until reconciled.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical Anthropic catalog (pricing) facts extracted from the official "
            "Anthropic pricing docs. Generated by update/extract_anthropic_catalog.py — "
            "do not hand-edit; refresh by running that script. Pricing facts only; tier "
            "ratings + benchmarks are the catalog cron's lane. Consumed OFFLINE by "
            "update/validate_catalog_conformance.py (price-provenance check)."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        # price-only: Anthropic models ARE on Cursor's pricing page, so the cron
        # keeps maintaining their <model> elements (tier ratings + benchmarks).
        # This source is authoritative for PRICE only (enforced by the G4
        # price-provenance gate); the federation overlay must NOT force/freeze
        # these elements.
        "overlay_mode": "price-only",
        "models": models,
        "slug_to_id": {str(m["slug"]): str(m["id"]) for m in models},
        "unexpected_slugs": [],
        "missing_mapped_models": missing,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Anthropic model + pricing facts from the pricing docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="pricing Markdown endpoint to fetch")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read Markdown from a local file instead of fetching (for tests)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="where to write the JSON snapshot (default: committed canonical copy)",
    )
    args = parser.parse_args()

    try:
        md = args.input.read_text() if args.input else fetch_text(args.url)
    except Exception as exc:
        print(f"extract_anthropic_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(md, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_anthropic_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_anthropic_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
