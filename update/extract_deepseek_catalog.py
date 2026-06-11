"""Deterministically extract DeepSeek's catalog facts (models + pricing) from the
official DeepSeek pricing docs.

This is the catalog-lane analog of ``update/extract_deepseek_thinking.py`` and the
first **provider-direct catalog source** for the Phase 4.6 federation: it reads
DeepSeek's OWN pricing page (not Cursor's) and emits the canonical *pricing
facts* for each DeepSeek model — id, display name, input / output / cache-read $
per 1M, context window, max output. It is the promotion of the flag-only
``update/extract_deepseek_models.py`` (which only FLAGS new models) into a real
source.

Scope boundary (Phase 4.6 decision 2 — "re-source, don't re-shape"): this source
provides only the facts a *pricing page* can know. A model's S/A/B/C/D tier
ratings and ``headline-benchmarks`` are editorial / benchmark-derived (the
catalog cron's Opus pass owns them) and are NOT produced here. The cost *tier*
bucket (Low / Medium / High / Very High) is derived downstream by
``update/merge_catalog.py`` from the output price, not stored here.

Like the thinking extractor, ``api-docs.deepseek.com`` serves server-rendered
HTML (no clean ``.md``), so this parses the pricing table with BeautifulSoup; the
change-detection hash (``section_sha256``) is over the canonical extracted facts
(sorted JSON), not the raw HTML. The committed snapshot
(``update/catalog-deepseek.json``) is consumed offline by
``update/merge_catalog.py`` and ``update/validate_catalog_conformance.py``.

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
from bs4 import BeautifulSoup
from bs4.element import Tag

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-deepseek.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-deepseek.json"

DOCS_URL = "https://api-docs.deepseek.com/quick_start/pricing"
PROVIDER = "deepseek"
JURISDICTION = "cn"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Canonical model ids this source has seen (2026-06-11). A pricing-table model
# outside this set is FLAGGED in ``unexpected_slugs`` (a new model is reviewed
# editorially before it becomes recommendable — it needs tier ratings), never
# silently treated as canonical. Mirrors the reasoning extractor's guard.
KNOWN_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

# Slug (as printed in the pricing table MODEL row) -> canonical selector id.
# Committed + auditable per Phase 4.6 refinement 5a; identity today.
SLUG_TO_ID = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
}

# Literal server-rendered substrings that MUST survive on the page (verified in
# the raw HTML 2026-06-11). Their absence means a restructure -> fail loud.
REQUIRED_ANCHORS = (
    "MODEL",
    "deepseek-v4",
    "1M INPUT TOKENS",
    "1M OUTPUT TOKENS",
    "CONTEXT LENGTH",
)

_FOOTNOTE_RE = re.compile(r"\s*\(.*?\)\s*")
_DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
_TOKENS_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*([KMkm])")


class ExtractError(RuntimeError):
    """The pricing docs no longer match the structure this parser expects."""


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def verify_anchors(html: str) -> None:
    missing = [a for a in REQUIRED_ANCHORS if a not in html]
    if missing:
        raise ExtractError(f"expected pricing anchors missing (restructure?): {missing}")


def _row_cells(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]


def _pricing_table(soup: BeautifulSoup) -> Tag:
    """Return the table whose first row's first cell is ``MODEL``.

    Located by row CONTENT (not table index/CSS) so a layout change does not
    mis-select — the Gemini/DeepSeek HTML lesson.
    """
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
        if rows and _row_cells(rows[0])[:1] == ["MODEL"]:
            return table
    raise ExtractError("pricing table not found (no row whose first cell is 'MODEL')")


def _dollars(cell: str) -> float | None:
    m = _DOLLAR_RE.search(cell)
    return float(m.group(1)) if m else None


def _tokens(cell: str) -> int | None:
    m = _TOKENS_RE.search(cell)
    if not m:
        return None
    scale = 1_000_000 if m.group(2).upper() == "M" else 1_000
    return int(float(m.group(1)) * scale)


def _row_by_label(rows: list[Tag], *needles: str) -> list[str] | None:
    """First row whose JOINED cell text contains every needle (case-insensitive).

    Joins ALL cells (not just the first) so a row carrying a ``rowspan`` section
    label in cell 0 — e.g. the ``PRICING`` cell that spans the cache-hit row — is
    still matched by its real label in a later cell.
    """
    for row in rows:
        cells = _row_cells(row)
        joined = " ".join(cells).lower()
        if cells and all(n.lower() in joined for n in needles):
            return cells
    return None


def _per_model_values(
    cells: list[str] | None, pattern: re.Pattern[str], m: int
) -> list[str] | None:
    """Per-model value cells of a fact row, robust to ``rowspan`` + ``colspan``.

    Returns the cells matching ``pattern`` (a $ amount or a token count): ``m``
    matches -> positional per model; exactly 1 match -> a colspan-shared value
    broadcast to all ``m`` models (the DeepSeek table shares CONTEXT LENGTH /
    MAX OUTPUT across both models); anything else -> None.
    """
    if cells is None:
        return None
    matches = [c for c in cells if pattern.search(c)]
    if len(matches) == m:
        return matches
    if len(matches) == 1:
        return matches * m
    return None


def parse_pricing_table(soup: BeautifulSoup) -> list[dict[str, object]]:
    """Parse the DeepSeek pricing table into per-model canonical pricing facts.

    The MODEL row names the models; each labelled fact row supplies its value(s).
    Robust to the table's mixed layout: a ``rowspan`` ``PRICING`` cell shifts the
    price rows' columns, and CONTEXT / MAX OUTPUT use ``colspan`` to share one
    value — so values are matched by content ($/tokens), not fixed column index.
    Footnote markers (``(1)``) on the model slugs are stripped.
    """
    table = _pricing_table(soup)
    rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]

    model_cells = _row_cells(rows[0])  # ["MODEL", "<slug> (1)", "<slug>", ...]
    slugs = [_FOOTNOTE_RE.sub("", c).strip() for c in model_cells[1:] if c.strip()]
    if not slugs:
        raise ExtractError("pricing MODEL row has no model columns")
    m = len(slugs)

    inputs = _per_model_values(_row_by_label(rows, "input", "cache miss"), _DOLLAR_RE, m)
    outputs = _per_model_values(_row_by_label(rows, "output", "tokens"), _DOLLAR_RE, m)
    cache_hits = _per_model_values(_row_by_label(rows, "input", "cache hit"), _DOLLAR_RE, m)
    contexts = _per_model_values(_row_by_label(rows, "context length"), _TOKENS_RE, m)
    max_outs = _per_model_values(_row_by_label(rows, "max output"), _TOKENS_RE, m)
    version_row = _row_by_label(rows, "model version")
    versions = version_row[-m:] if version_row and len(version_row) >= m else None

    if inputs is None or outputs is None:
        raise ExtractError(
            "pricing table missing per-model INPUT (CACHE MISS) or OUTPUT TOKENS prices"
        )

    models: list[dict[str, object]] = []
    for i, slug in enumerate(slugs):
        in_price = _dollars(inputs[i])
        out_price = _dollars(outputs[i])
        if in_price is None or out_price is None:
            raise ExtractError(f"could not parse input/output price for {slug!r}")
        models.append(
            {
                "id": SLUG_TO_ID.get(slug, slug),
                "slug": slug,
                "name": (versions[i].strip() if versions else slug) or slug,
                "input_price_per_1m": in_price,
                "output_price_per_1m": out_price,
                "cache_read_per_1m": _dollars(cache_hits[i]) if cache_hits else None,
                "context_tokens": _tokens(contexts[i]) if contexts else None,
                "max_output_tokens": _tokens(max_outs[i]) if max_outs else None,
            }
        )
    return models


def canonical_facts(models: list[dict[str, object]]) -> str:
    return json.dumps(
        {"provider": PROVIDER, "jurisdiction": JURISDICTION, "models": models},
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(html: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(html)
    soup = BeautifulSoup(html, "html.parser")
    models = parse_pricing_table(soup)

    unexpected = sorted({str(m["id"]) for m in models} - KNOWN_MODELS)
    if unexpected:
        print(
            f"extract_deepseek_catalog: NOTE unexpected DeepSeek model(s) not in the "
            f"known baseline {sorted(KNOWN_MODELS)}: {unexpected}. A new model needs "
            f"editorial tier ratings before it is recommendable — flag for review; "
            f"do NOT auto-add it to the selector.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical DeepSeek catalog (pricing) facts extracted from the official "
            "DeepSeek pricing docs. Generated by update/extract_deepseek_catalog.py — "
            "do not hand-edit; refresh by running that script. Pricing facts only; "
            "tier ratings + benchmarks are editorial (the catalog cron's lane). "
            "Consumed OFFLINE by update/merge_catalog.py + "
            "update/validate_catalog_conformance.py."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        "models": models,
        "slug_to_id": dict(sorted(SLUG_TO_ID.items())),
        "unexpected_slugs": unexpected,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract DeepSeek model + pricing facts from the pricing docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="pricing HTML endpoint to fetch")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read HTML from a local file instead of fetching (for tests)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="where to write the JSON snapshot (default: committed canonical copy)",
    )
    args = parser.parse_args()

    try:
        html = args.input.read_text() if args.input else fetch_html(args.url)
    except Exception as exc:
        print(f"extract_deepseek_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(html, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_deepseek_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_deepseek_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
