"""Deterministically extract z.ai (Zhipu AI) catalog facts (models + pricing) from
the official z.ai pricing docs.

A provider-direct catalog source for the Phase 4.6 federation (the GLM analog of
``update/extract_deepseek_catalog.py``): it reads z.ai's OWN pricing page — and,
unlike DeepSeek, z.ai exposes a clean Mintlify ``.md`` source
(``docs.z.ai/guides/overview/pricing.md``) whose Markdown pricing table is
trivially parseable and immune to frontend rebuilds (the same property the Cursor
``.md`` source relies on). So this parses the Markdown table directly — no
BeautifulSoup needed.

Scope boundary (Phase 4.6 decision 2 — "re-source, don't re-shape"): this source
provides only the facts a *pricing page* can know — id, display name, input /
output / cache-read $ per 1M. A model's S/A/B/C/D tier ratings and
``headline-benchmarks`` are editorial (the catalog cron's Opus pass owns them) and
are NOT produced here. The cost *tier* bucket (Low / Medium / High / Very High) is
derived downstream by ``update/merge_catalog.py`` from the output price.

z.ai publishes a large lineup (~17 priced text + vision models plus image / video
/ audio). roadmodel's catalog is CURATED (DeepSeek ships 2, Mistral 4): only the
``CURATED`` allow-list below is emitted into ``catalog-zai.json``; every other
text-model slug on the page is recorded in ``unexpected_slugs`` so a genuinely new
flagship (e.g. a future GLM-6) is flagged for editorial review without auto-adding
it. Free-tier rows (``Free`` / ``$0`` output) are naturally excluded — they are
not in ``CURATED`` and would fail the conformance gate's positive-price check.

The change-detection hash (``section_sha256``) is over the canonical extracted
facts (sorted JSON), not the raw Markdown. The committed snapshot
(``update/catalog-zai.json``) is consumed offline by ``update/merge_catalog.py``
and ``update/validate_catalog_conformance.py``.

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (the docs were
restructured so the deterministic parse no longer finds what it expects, or a
CURATED model vanished from the page).
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
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-zai.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-zai.json"

# Mintlify exposes the raw Markdown at the ``.md`` URL (immune to frontend
# rebuilds; mirrors update/sources.json's note on the Cursor ``.md`` source).
DOCS_URL = "https://docs.z.ai/guides/overview/pricing.md"
PROVIDER = "zai"
JURISDICTION = "cn"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Every TEXT-model slug seen on the pricing page (2026-06-21). A text-model slug
# outside this baseline is FLAGGED in ``unexpected_slugs`` (a new model is reviewed
# editorially before it becomes recommendable — it needs tier ratings), never
# silently treated as canonical. Mirrors the DeepSeek extractor's guard.
KNOWN_MODELS = frozenset(
    {
        "GLM-5.2",
        "GLM-5.1",
        "GLM-5",
        "GLM-5-Turbo",
        "GLM-4.7",
        "GLM-4.7-FlashX",
        "GLM-4.6",
        "GLM-4.5",
        "GLM-4.5-X",
        "GLM-4.5-Air",
        "GLM-4.5-AirX",
        "GLM-4-32B-0414-128K",
        "GLM-4.7-Flash",
        "GLM-4.5-Flash",
    }
)

# The curated subset roadmodel surfaces in the selector: the current flagship, the
# proven value coding workhorse, and the budget tier. Slug (as printed in the
# pricing table) -> canonical selector id.
CURATED = {
    "GLM-5.2": "glm-5.2",
    "GLM-4.6": "glm-4.6",
    "GLM-4.5-Air": "glm-4.5-air",
}

# Literal substrings that MUST survive on the page (verified 2026-06-21). Their
# absence means a restructure -> fail loud rather than silently emit nothing.
REQUIRED_ANCHORS = (
    "# Pricing",
    "### Text Models",
    "Prices per 1M tokens",
    "| Model",
    "GLM-5.2",
    "GLM-4.6",
    "GLM-4.5-Air",
)

_PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")


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


def _price(cell: str) -> float | None:
    """Parse a Markdown price cell to a float, or None for Free / '-' / blank.

    The page escapes dollar signs (``\\$1.4``); ``_PRICE_RE`` matches the digits
    after the (possibly escaped) ``$``.
    """
    m = _PRICE_RE.search(cell)
    return float(m.group(1)) if m else None


def _section_table_rows(md: str, header: str) -> list[list[str]]:
    """Return the data rows (as cell lists) of the first Markdown pipe-table that
    follows ``header`` (e.g. ``### Text Models``).

    The table is the run of consecutive ``|``-leading lines after the header; row 0
    is the column header, row 1 the ``|:---|`` separator, the rest are data. Located
    by section header CONTENT, not position, so reordering sections does not
    mis-select.
    """
    start = md.find(header)
    if start == -1:
        raise ExtractError(f"section header not found: {header!r}")
    rows: list[list[str]] = []
    in_table = False
    for line in md[start + len(header) :].splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            in_table = True
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            rows.append(cells)
        elif in_table and not stripped:
            break  # blank line ends the table
    if len(rows) < 3:
        raise ExtractError(f"no parseable table under {header!r}")
    # Drop the header row and the |:---| separator row.
    return rows[2:]


def parse_text_models(md: str) -> tuple[list[dict[str, object]], list[str]]:
    """Parse the Text Models pricing table.

    Returns ``(curated_models, page_slugs)`` — ``curated_models`` are the CURATED
    rows with valid input + output prices; ``page_slugs`` is every text-model slug
    seen (for the unexpected-slug discovery flag).
    """
    rows = _section_table_rows(md, "### Text Models")
    page_slugs: list[str] = []
    by_slug: dict[str, dict[str, object]] = {}
    for cells in rows:
        if len(cells) < 5:
            continue
        slug = cells[0].strip()
        if not slug:
            continue
        page_slugs.append(slug)
        in_price = _price(cells[1])
        cache_price = _price(cells[2])
        out_price = _price(cells[4])
        if in_price is None or out_price is None:
            continue  # Free / unpriced row — never curated
        by_slug[slug] = {
            "id": CURATED.get(slug, slug),
            "slug": slug,
            "name": slug,
            "input_price_per_1m": in_price,
            "output_price_per_1m": out_price,
            "cache_read_per_1m": cache_price,
        }

    missing = [slug for slug in CURATED if slug not in by_slug]
    if missing:
        raise ExtractError(
            f"curated z.ai model(s) missing/unpriced on the pricing page: {missing} "
            f"(delisting/rename? re-verify CURATED)"
        )
    curated = [by_slug[slug] for slug in CURATED]
    return curated, page_slugs


def canonical_facts(models: list[dict[str, object]]) -> str:
    return json.dumps(
        {"provider": PROVIDER, "jurisdiction": JURISDICTION, "models": models},
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(md: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(md)
    models, page_slugs = parse_text_models(md)

    unexpected = sorted(set(page_slugs) - KNOWN_MODELS)
    if unexpected:
        print(
            f"extract_zai_catalog: NOTE text model(s) on the page not in the known "
            f"baseline: {unexpected}. A new model needs editorial tier ratings before "
            f"it is recommendable — flag for review; do NOT auto-add it to the selector.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical z.ai (Zhipu AI) catalog (pricing) facts extracted from the "
            "official z.ai pricing docs (Mintlify .md source). Generated by "
            "update/extract_zai_catalog.py — do not hand-edit; refresh by running that "
            "script. Pricing facts only; tier ratings + benchmarks are editorial (the "
            "catalog cron's lane). Only the CURATED subset is emitted (z.ai ships ~17 "
            "priced models); other text slugs are recorded in unexpected_slugs for "
            "editorial review. Consumed OFFLINE by update/merge_catalog.py + "
            "update/validate_catalog_conformance.py."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        # whole-element: z.ai is NOT on Cursor's pricing page, so the cron's Opus
        # rewrite drops it — the federation overlay re-adds the full <model> element
        # (incl. its editorial tier ratings) from the committed selector.
        "overlay_mode": "whole-element",
        "models": models,
        "slug_to_id": dict(sorted(CURATED.items())),
        "unexpected_slugs": unexpected,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract z.ai (GLM) model + pricing facts from the pricing docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="pricing .md endpoint to fetch")
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
        print(f"extract_zai_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(md, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_zai_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_zai_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
