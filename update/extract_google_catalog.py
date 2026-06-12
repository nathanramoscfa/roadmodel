"""Deterministically extract Google's catalog (pricing) facts from the official
Gemini API pricing docs.

Phase 4.6 T3 — the Google analog of the other provider-direct catalog sources.
``ai.google.dev/gemini-api/docs/pricing`` is server-rendered HTML (the same host
the Gemini *dial* tracker parses with bs4) and is laid out as **per-model
sections**: a model heading (e.g. ``Gemini 3.5 Flash``) above per-tier
sub-sections (``Standard`` / ``Batch`` / ``Flex`` / ``Priority``), each a small
table with ``Input price`` / ``Output price`` rows in a ``Free Tier`` /
``Paid Tier`` column pair. This parser walks those sections and reads the
**Standard / Paid-Tier** input & output price for each selector model.

Makes **Google's own page authoritative** for Gemini prices (enforced by the G4
price-provenance check). Pricing facts only (``overlay_mode: price-only``); tier
ratings + benchmarks stay Cursor-maintained.

Disambiguation matters: model headings carry suffixes (``Gemini 3.1 Pro
Preview``) and near-misses exist (``Gemini 3 Pro Image``, ``Gemini 2.5
Flash-Lite``). We strip a trailing `` Preview`` and then EXACT-match the display
name, and stop at any non-target ``Gemini …`` h2 so a table never binds to the
wrong model. Pro pricing is context-tiered (≤200K vs >200K); the FIRST Standard
table per model is the ≤200K (headline) tier the selector carries.
``gemini-3-pro`` has no standalone heading today (only ``Gemini 3 Pro Image``), so
it stays Cursor-sourced (``missing_mapped_models``).

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (restructure).
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
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-google.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-google.json"

DOCS_URL = "https://ai.google.dev/gemini-api/docs/pricing"
PROVIDER = "google"
JURISDICTION = "us"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Gemini pricing-section model heading (trailing " Preview" stripped) -> selector
# id. EXACT match only, so near-misses (Gemini 3 Pro Image, 2.5 Flash-Lite, 2.5
# Flash Image, …) do NOT bind. gemini-3-pro has no standalone heading today.
NAME_TO_ID = {
    "Gemini 3.1 Pro": "gemini-3.1-pro",
    "Gemini 3 Pro": "gemini-3-pro",
    "Gemini 3.5 Flash": "gemini-3.5-flash",
    "Gemini 3 Flash": "gemini-3-flash",
    "Gemini 2.5 Flash": "gemini-2.5-flash",
}
ID_TO_NAME = {v: k for k, v in NAME_TO_ID.items()}

REQUIRED_ANCHORS = (
    "Gemini 3.1 Pro",
    "Gemini 2.5 Flash",
    "Input price",
    "Paid Tier",
)

_DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
_PREVIEW_RE = re.compile(r"\s+Preview$")


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


def _dollars(cell: str) -> float | None:
    m = _DOLLAR_RE.search(cell)
    return float(m.group(1)) if m else None


def _tier_of(table: Tag) -> str:
    h = table.find_previous(["h1", "h2", "h3", "h4"])
    return h.get_text(" ", strip=True) if isinstance(h, Tag) else ""


def _model_id_for(table: Tag) -> str | None:
    """The selector id of the model whose section this table is in, or None.

    Walks preceding headings nearest-first: a `` Preview``-stripped exact match to
    a target display name wins; hitting a NON-target ``Gemini …`` h2 first means
    the table belongs to another model (stop — do not bind it to a target above).
    """
    for h in table.find_all_previous(["h1", "h2", "h3", "h4"]):
        if not isinstance(h, Tag):
            continue
        txt = _PREVIEW_RE.sub("", h.get_text(" ", strip=True)).strip()
        if txt in NAME_TO_ID:
            return NAME_TO_ID[txt]
        if h.name == "h2" and txt.startswith("Gemini "):
            return None
    return None


def parse_pricing(soup: BeautifulSoup) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        rows = [_row_cells(r) for r in table.find_all("tr") if isinstance(r, Tag)]
        has_in = any(c and "input price" in c[0].lower() for c in rows)
        has_out = any(c and c[0].lower().startswith("output price") for c in rows)
        if not (has_in and has_out):
            continue
        if _tier_of(table).lower() != "standard":
            continue
        mid = _model_id_for(table)
        if mid is None or mid in seen:
            continue
        in_price = out_price = None
        for c in rows:
            if not c:
                continue
            if "input price" in c[0].lower():
                in_price = _dollars(c[-1])  # last column = Paid Tier
            elif c[0].lower().startswith("output price"):
                out_price = _dollars(c[-1])
        if in_price is None or out_price is None:
            raise ExtractError(f"could not parse Standard input/output price for {mid!r}")
        seen.add(mid)
        name = ID_TO_NAME[mid]
        models.append(
            {
                "id": mid,
                "slug": name,
                "name": name,
                "input_price_per_1m": in_price,
                "output_price_per_1m": out_price,
                "cache_read_per_1m": None,
            }
        )
    if not models:
        raise ExtractError("no mapped Gemini models found in the Standard pricing sections")
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
    models = parse_pricing(soup)

    found = {str(m["id"]) for m in models}
    missing = sorted(set(NAME_TO_ID.values()) - found)
    if missing:
        print(
            f"extract_google_catalog: NOTE mapped selector model(s) with no standalone "
            f"Standard pricing section: {missing} (e.g. gemini-3-pro — only 'Gemini 3 Pro "
            f"Image' is listed). Their price stays Cursor-sourced until reconciled.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical Google (Gemini) catalog (pricing) facts extracted from the official "
            "Gemini API pricing docs (per-model Standard / Paid-Tier). Generated by "
            "update/extract_google_catalog.py — do not hand-edit; refresh by running that "
            "script. Pricing facts only; tier ratings + benchmarks are the catalog cron's "
            "lane. Consumed OFFLINE by update/validate_catalog_conformance.py "
            "(price-provenance check)."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        # price-only: Gemini models are on Cursor's page; their <model> elements +
        # benchmark ratings stay Cursor-maintained. Authoritative for PRICE only
        # (G4). The federation overlay must NOT force these elements.
        "overlay_mode": "price-only",
        "models": models,
        "slug_to_id": {str(m["slug"]): str(m["id"]) for m in models},
        "unexpected_slugs": [],
        "missing_mapped_models": missing,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Gemini model + pricing facts from the Gemini API pricing docs."
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
        print(f"extract_google_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(html, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_google_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_google_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
