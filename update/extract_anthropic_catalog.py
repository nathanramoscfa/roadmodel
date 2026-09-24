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
    # Added 2026-09-05: all three are IN <model-options> and recommended, but
    # were never mapped here, so their prices came from the aggregator mirror
    # with no provider-direct verification (exactly what G5 flags).
    "Claude Fable 5.1": "claude-fable-5.1",
    # Added 2026-09-23 with its catalog entry: the Opus 5 successor ($4/$20),
    # Claude Code's default Opus from 2.1.280. Mapping it is what makes its
    # price provider-verified (G4) instead of trusted from the aggregator, and
    # what stops the extractor flagging a model the catalog now carries.
    "Claude Opus 5.5": "claude-opus-5-5",
    "Claude Opus 5": "claude-opus-5",
    "Claude Sonnet 5": "claude-sonnet-5",
    "Claude Fable 5": "claude-fable-5",
    "Claude Opus 4.8": "opus-4.8",
    "Claude Opus 4.7": "opus-4.7",
    "Claude Sonnet 4.6": "sonnet-4.6",
    "Claude Haiku 4.5": "claude-4.5-haiku",
}

# Literal substrings that MUST survive in the Markdown. Their absence means a
# restructure -> fail loud rather than emit a partial/empty snapshot.
REQUIRED_ANCHORS = (
    "ase input tokens",  # case-insensitively; the page restyled this in 2026-08
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
    """Fail loud if the page no longer looks like the pricing doc.

    Matched case-insensitively: a restyled heading is not a restructure, and
    treating it as one cost this source three weeks of silent staleness.
    """
    lowered = md.lower()
    missing = [a for a in REQUIRED_ANCHORS if a.lower() not in lowered]
    if missing:
        raise ExtractError(f"expected anchors missing (restructure?): {missing}")


def _dollars(cell: str) -> float | None:
    m = _DOLLAR_RE.search(cell)
    return float(m.group(1)) if m else None


def _col(header: list[str], *needles: str) -> int | None:
    for i, h in enumerate(header):
        if all(n.lower() in h.lower() for n in needles):
            return i
    return None


# DISCOVERY: a priced row this page carries that the catalog neither maps
# (``NAME_TO_ID``) nor declines below is reported in ``unexpected_slugs`` — the
# catalog cron's model-discovery input (update/prompt.md). Without it a new
# Claude model reaches the catalog only if Cursor happens to list it, which is
# how gpt-6-astra went unnoticed on the OpenAI lane. Each DECLINED entry is a
# model Anthropic prices that the catalog deliberately does not carry.
DECLINED = {
    "Claude Opus 4.6": "superseded by Opus 4.7 / 4.8 / 5",
    "Claude Opus 4.5": "superseded by Opus 4.7 / 4.8 / 5",
    "Claude Sonnet 4.5": "superseded by Sonnet 4.6 / 5",
    "Claude Opus 4": "retired",
    "Claude Opus 4.1": "retired",
    "Claude Sonnet 4": "retired",
    "Claude Haiku 3.5": "retired",
}

# "Claude Haiku 3.5 ([retired, …](…))" → "Claude Haiku 3.5".
_ROW_NOTE_RE = re.compile(r"\s*\(\[.*$")


def discover_unmapped(md: str) -> list[str]:
    """Priced rows the catalog neither maps nor declines — models that exist
    and are priced but that roadmodel has never heard of."""
    header, data = _pricing_table(md)
    del header
    found: set[str] = set()
    for row in data:
        if not row:
            continue
        name = _ROW_NOTE_RE.sub("", row[0].strip()).strip()
        # Footnote rows list several models in one cell ("Opus 5, Opus 4.8, and
        # Claude Opus 4.7"); they price nothing new.
        if not name or "," in name or "/" in name or " and " in name:
            continue
        if name in NAME_TO_ID or name in DECLINED:
            continue
        found.add(name)
    return sorted(found)


def discovered_prices(md: str, names: list[str]) -> list[dict[str, object]]:
    """Each flagged row with the base input and output price the standard
    table quotes for it, so the catalog cron can add it at Anthropic's own
    price. A row whose cells do not parse is listed without a price."""
    header, data = _pricing_table(md)
    in_col = _col(header, "Input")
    out_col = _col(header, "Output")
    wanted = set(names)
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in data:
        if not row:
            continue
        name = _ROW_NOTE_RE.sub("", row[0].strip()).strip()
        if name not in wanted or name in seen:
            continue
        seen.add(name)
        entry: dict[str, object] = {"slug": name}
        in_price = _dollars(row[in_col]) if in_col is not None and in_col < len(row) else None
        out_price = _dollars(row[out_col]) if out_col is not None and out_col < len(row) else None
        if in_price is not None and out_price is not None:
            entry["input_price_per_1m"] = in_price
            entry["output_price_per_1m"] = out_price
        out.append(entry)
    return out


def _pricing_table(md: str) -> tuple[list[str], list[list[str]]]:
    """(header cells, data rows) of the standard per-token pricing table —
    the one whose header carries ``Base Input Tokens`` … ``Output Tokens``.
    The fast-mode / batch tables (which lack that header) are ignored."""
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
            # Case-INSENSITIVE: Anthropic restyled the header to "Base input
            # tokens" in 2026-08, and the exact-case check then failed for every
            # run. The cron's per-provider fail-open swallowed it, so the
            # committed snapshot silently froze — which is how claude-sonnet-5
            # kept an aggregator-mirror price of $3/$15 while Anthropic's own
            # page said $2/$10, and how Opus 5 / Sonnet 5 / Fable 5.1 stayed
            # absent from the provider-direct source entirely.
            lowered = [c.lower() for c in cells]
            if "base input tokens" in lowered and "output tokens" in lowered:
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):  # the |---|---| separator
            continue
        data.append(cells)

    if header is None:
        raise ExtractError(
            "standard Anthropic pricing table not found (no 'Base Input Tokens' header)"
        )
    return header, data


def parse_pricing_table(md: str) -> list[dict[str, object]]:
    """Per-model canonical pricing facts for the models the catalog maps."""
    header, data = _pricing_table(md)
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
        name = row[0].strip()
        mid = NAME_TO_ID.get(name)
        if mid is None or mid in seen:
            continue
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


def build_snapshot(md: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(md)
    models = parse_pricing_table(md)
    unexpected = discover_unmapped(md)
    if unexpected:
        print(
            "extract_anthropic_catalog: DISCOVERY — the pricing table prices "
            f"model(s) the catalog does not carry: {unexpected}. They are "
            "reported in unexpected_slugs for the catalog cron to add or decline.",
            file=sys.stderr,
        )

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
        "unexpected_slugs": unexpected,
        # The flagged rows' own prices, for the catalog cron's discovery lane
        # (update/discovery.py hands them to the curation model).
        "discovered": discovered_prices(md, unexpected),
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
