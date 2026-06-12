"""Deterministically extract OpenAI's catalog (pricing) facts from the official
OpenAI API pricing docs.

Phase 4.6 T3 — the OpenAI analog of ``extract_anthropic_catalog.py``. OpenAI
publishes pricing at ``platform.openai.com/docs/pricing.md`` (redirects to
``developers.openai.com/api/docs/pricing.md``); unlike Anthropic's Markdown
table, the data is embedded as **JS/JSX arrays** ``["<name>", input, cached,
output]`` inside ``<TextTokenPricingTables ... rows={[ ... ]}>`` components, with
several priced panes (``standard`` / ``batch`` / ``priority`` / ``flex``). This
parser scopes to the **standard** pane (``data-value="standard"``) and ignores
the discounted ones.

Makes **OpenAI's own page authoritative** for its prices (enforced by the G4
price-provenance check in ``update/validate_catalog_conformance.py``). Pricing
facts only (``overlay_mode: price-only``); tier ratings + benchmarks stay
Cursor-maintained.

Only the selector's NON-codex GPT models are mapped — the Codex variants
(``gpt-5.3-codex`` / ``gpt-5.1-codex``) are NOT listed on the standard API
pricing page, so they stay Cursor-sourced (recorded in
``missing_mapped_models``) until a Codex pricing source is added.

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
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-openai.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-openai.json"

DOCS_URL = "https://platform.openai.com/docs/pricing.md"
PROVIDER = "openai"
JURISDICTION = "us"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Standard-pane model name (parenthetical context suffix stripped) -> selector id.
# ONLY the NON-codex GPT models the selector recommends. The Codex variants are
# not on this page (see module docstring).
NAME_TO_ID = {
    "gpt-5.5": "gpt-5.5",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-nano": "gpt-5.4-nano",
    "gpt-5.2": "gpt-5.2",
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
}

# Literal substrings that MUST survive in the docs. Their absence means a
# restructure -> fail loud rather than emit a partial/empty snapshot.
REQUIRED_ANCHORS = (
    'data-value="standard"',
    'tier="standard"',
    "gpt-5.5",
    "gpt-5.4-mini",
    "per 1M",
)

# A pricing row: ["<name>", <input>, <cached>, <output>].
_ROW_RE = re.compile(r'\[\s*"([^"]+)"\s*,\s*([^\]]+?)\s*\]')
_SUFFIX_RE = re.compile(r"\s*\(.*?\)\s*$")


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


def _num(token: str) -> float | None:
    token = token.strip().strip('"')
    try:
        return float(token)
    except ValueError:
        return None


def _standard_rows_blob(md: str) -> str:
    """The ``rows={[ ... ]}`` content of the STANDARD pricing table.

    Anchored on ``tier="standard"`` immediately followed by its ``rows`` array —
    NOT a bare ``data-value="standard"`` (which can appear in prose/comments) —
    and captured only up to that array's ``]}`` close, so the batch / priority /
    flex panes (discounted prices for the SAME model names) are excluded.
    """
    m = re.search(r'tier="standard".*?rows=\{\[(.*?)\]\s*\}', md, re.DOTALL)
    if not m:
        raise ExtractError('standard pricing rows (tier="standard" rows={[...]}) not found')
    return m.group(1)


def parse_pricing(md: str) -> list[dict[str, object]]:
    span = _standard_rows_blob(md)
    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for name, rest in _ROW_RE.findall(span):
        canonical = _SUFFIX_RE.sub("", name).strip()
        mid = NAME_TO_ID.get(canonical)
        if mid is None or mid in seen:
            continue
        parts = [p.strip() for p in rest.split(",")]
        if len(parts) < 3:
            continue
        in_price = _num(parts[0])
        cache_price = _num(parts[1])
        out_price = _num(parts[-1])
        if in_price is None or out_price is None:
            raise ExtractError(f"could not parse input/output price for {name!r}")
        seen.add(mid)
        models.append(
            {
                "id": mid,
                "slug": canonical,
                "name": canonical,
                "input_price_per_1m": in_price,
                "output_price_per_1m": out_price,
                "cache_read_per_1m": cache_price,
            }
        )
    if not models:
        raise ExtractError("no mapped OpenAI models found in the standard pricing pane")
    return models


def canonical_facts(models: list[dict[str, object]]) -> str:
    return json.dumps(
        {"provider": PROVIDER, "jurisdiction": JURISDICTION, "models": models},
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(md: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(md)
    models = parse_pricing(md)

    found = {str(m["id"]) for m in models}
    missing = sorted(set(NAME_TO_ID.values()) - found)
    if missing:
        print(
            f"extract_openai_catalog: NOTE mapped selector model(s) not found in the "
            f"standard pane (renamed?): {missing}. Their price stays Cursor-sourced.",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical OpenAI catalog (pricing) facts extracted from the official OpenAI "
            "API pricing docs (standard pane). Generated by update/extract_openai_catalog.py "
            "— do not hand-edit; refresh by running that script. Pricing facts only; tier "
            "ratings + benchmarks are the catalog cron's lane. The Codex variants "
            "(gpt-5.3-codex / gpt-5.1-codex) are not on this page and stay Cursor-sourced. "
            "Consumed OFFLINE by update/validate_catalog_conformance.py (price-provenance)."
        ),
        "source_url": source_url,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        # price-only: OpenAI GPT models are on Cursor's page, so their <model>
        # elements + benchmark ratings stay Cursor-maintained; this source is
        # authoritative for PRICE only (G4). The federation overlay must NOT force
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
        description="Extract OpenAI model + pricing facts from the API pricing docs."
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
        print(f"extract_openai_catalog: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(md, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_openai_catalog: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    models = snapshot["models"]
    summary = ", ".join(str(m["id"]) for m in models) if isinstance(models, list) else str(models)
    print(f"extract_openai_catalog: wrote {args.output} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
