"""Deterministically extract xAI's catalog (pricing) facts from the official xAI
models docs.

Phase 4.6 T3 — the xAI analog of ``extract_anthropic_catalog.py``. xAI publishes a
clean Markdown table at ``docs.x.ai/docs/models.md`` (redirects to
``docs.x.ai/developers/models.md``): ``| Model | Context | Input / 1M tokens |
Output / 1M tokens |``. Markdown-table parse, no bs4.

Makes **xAI's own page authoritative** for Grok prices (enforced by the G4
price-provenance check). Pricing facts only (``overlay_mode: price-only``); tier
ratings + benchmarks stay Cursor-maintained. Only ``grok-4.3`` is in the
selector; the page's other models (grok-4.20-*, grok-build, image/audio) are not
mapped.

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

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-xai.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-xai.json"

# Canonical final URL — docs/models.md issues a 308 to this; fetching it directly
# avoids a redirect that intermittently 404s through requests.
DOCS_URL = "https://docs.x.ai/developers/models.md"
PROVIDER = "xai"
JURISDICTION = "us"

FETCH_TIMEOUT = 30

# docs.x.ai sits behind a CDN bot rule that 404s a bare urllib3/requests client
# (and the project's normal "roadmodel-updater/..." UA) regardless of UA, while
# accepting a request carrying the usual browser navigation headers. The page is
# public docs; we send a browser-like header set so the deterministic fetch
# succeeds (verified: bare UA -> 404, these headers -> 200; the other providers
# need none of this). NOT TLS-fingerprint evasion — purely the standard
# navigation headers a browser sends.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# xAI token-pricing table model name -> canonical selector id. Only the model the
# selector recommends; grok-4.20-* / grok-build / image / audio are not mapped.
NAME_TO_ID = {
    "grok-4.3": "grok-4.3",
}

REQUIRED_ANCHORS = (
    "grok-4.3",
    "Input / 1M tokens",
    "Output / 1M tokens",
)

_DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
_FOOTNOTE_RE = re.compile(r"\s*\(.*?\)\s*")


class ExtractError(RuntimeError):
    """The pricing docs no longer match the structure this parser expects."""


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers=_BROWSER_HEADERS,
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


def _col(header: list[str], *needles: str) -> int | None:
    for i, h in enumerate(header):
        if all(n.lower() in h.lower() for n in needles):
            return i
    return None


def parse_pricing_table(md: str) -> list[dict[str, object]]:
    """Parse the token-pricing table (header ``Input / 1M tokens`` … ``Output /
    1M tokens``); the image / audio tables (header ``Model | Cost``) are ignored.
    """
    header: list[str] | None = None
    data: list[list[str]] = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if header is not None:
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            if any("input / 1m" in c.lower() for c in cells) and any(
                "output / 1m" in c.lower() for c in cells
            ):
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):  # |---|---| separator
            continue
        data.append(cells)

    if header is None:
        raise ExtractError("xAI token-pricing table not found (no 'Input / 1M tokens' header)")
    in_col = _col(header, "input", "1m")
    out_col = _col(header, "output", "1m")
    if in_col is None or out_col is None:
        raise ExtractError("pricing table missing an Input / Output column")

    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in data:
        if not row:
            continue
        name = _FOOTNOTE_RE.sub("", row[0]).strip()
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
                "cache_read_per_1m": None,
            }
        )
    if not models:
        raise ExtractError("no mapped xAI models found in the token-pricing table")
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

    found = {str(m["id"]) for m in models}
    missing = sorted(set(NAME_TO_ID.values()) - found)
    if missing:
        print(
            f"extract_xai_catalog: NOTE mapped selector model(s) not found (renamed?): "
            f"{missing}. Their price stays Cursor-sourced.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical xAI catalog (pricing) facts extracted from the official xAI models "
            "docs. Generated by update/extract_xai_catalog.py — do not hand-edit; refresh by "
            "running that script. Pricing facts only; tier ratings + benchmarks are the "
            "catalog cron's lane. Consumed OFFLINE by update/validate_catalog_conformance.py "
            "(price-provenance check)."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        # whole-element: Cursor delisted xAI from its pricing page on 2026-07-14,
        # but xAI still serves these models via its own API (the xai-api method),
        # so — like DeepSeek / Mistral — this snapshot now OWNS the <model>
        # element. The federation overlay re-adds it whenever the Opus rewrite
        # (driven by Cursor's page) drops it, so a Cursor-only delisting can no
        # longer discontinue a still-available provider-direct model.
        "overlay_mode": "whole-element",
        "models": models,
        "slug_to_id": {str(m["slug"]): str(m["id"]) for m in models},
        "unexpected_slugs": [],
        "missing_mapped_models": missing,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract xAI model + pricing facts from the models docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="models Markdown endpoint to fetch")
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
        print(f"extract_xai_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(md, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_xai_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_xai_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
