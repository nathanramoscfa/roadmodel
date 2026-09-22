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

Only the selector's NON-codex GPT models are mapped. The Codex variants
(``gpt-5.3-codex`` / ``gpt-5.1-codex``) are deliberately NOT mapped and by design
have NO provider-direct source: OpenAI does not publish a clean per-token USD
price for those SKUs. The standard API pricing page omits them; the dedicated
Codex pages (``developers.openai.com/codex/pricing`` + the help-center rate card)
price the Codex *product* in credits against base models (GPT-5.5 / 5.4), not the
gpt-5.3-codex / gpt-5.1-codex SKUs; and the third-party USD figures come from
aggregators, which federation rejects (same bug, new landlord). So they stay
Cursor-sourced — Cursor's pool price is authoritative for them — an INTENTIONAL
exception, not a pending gap. They are absent from ``NAME_TO_ID`` so they are not
falsely flagged as ``missing_mapped_models`` (a rename/drift detector for models
the standard page IS expected to price).

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

# platform.openai.com/docs/pricing.md 301s here; pin the canonical target.
DOCS_URL = "https://developers.openai.com/api/docs/pricing.md"
PROVIDER = "openai"
JURISDICTION = "us"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Standard-pane model name (parenthetical context suffix stripped) -> selector id.
# ONLY the NON-codex GPT models the selector recommends. The Codex variants are
# not on this page (see module docstring).
# DISCOVERY (the reason gpt-6-astra sat unnoticed for weeks): every row this
# page prices that is NOT in NAME_TO_ID used to be dropped in silence, so a
# brand-new OpenAI model could only reach the catalog if CURSOR happened to
# list it. A text row that is neither mapped below nor declined here is now
# reported in ``unexpected_slugs`` — the catalog cron's discovery input
# (update/prompt.md) and the G1 conformance contract already understand that
# field. Keep DECLINED explicit: each entry is a model OpenAI prices that the
# catalog deliberately does not carry, with the reason, so the flag list stays
# signal.
DECLINED = {
    # Superseded generations the selector no longer recommends.
    "gpt-4.1": "superseded by the GPT-5 line",
    "gpt-4.1-mini": "superseded by the GPT-5 line",
    "gpt-4.1-nano": "superseded by the GPT-5 line",
    "gpt-4o": "superseded by the GPT-5 line",
    "gpt-4o-mini": "superseded by the GPT-5 line",
    "gpt-4-turbo": "superseded by the GPT-5 line",
    "gpt-4": "superseded by the GPT-5 line",
    "gpt-3.5-turbo": "superseded by the GPT-5 line",
    "gpt-3.5-turbo-instruct": "superseded by the GPT-5 line",
    "davinci-002": "legacy completions model",
    "babbage-002": "legacy completions model",
    "o1": "superseded reasoning series",
    "o1-pro": "superseded reasoning series",
    "o3": "superseded reasoning series",
    "o3-pro": "superseded reasoning series",
    "o3-mini": "superseded reasoning series",
    "o4-mini": "superseded reasoning series",
    # `-pro` variants are a long-running batch mode of a model already carried,
    # not a separate model the selector picks between.
    "gpt-5-pro": "pro long-running variant of a carried model",
    "gpt-5.2-pro": "pro long-running variant of a carried model",
    "gpt-5.4-pro": "pro long-running variant of a carried model",
    "gpt-5.5-pro": "pro long-running variant of a carried model",
    # Carried only as their Codex variants (OpenAI prices Codex in credits).
    "gpt-5.1": "catalogued as gpt-5.1-codex / gpt-5.1-codex-max",
    "gpt-5-nano": "catalogued as gpt-5.4-nano's predecessor; not recommended",
}

# A dated pin ("gpt-4o-2024-05-13", "gpt-4-0613") is the same model as its base
# row; strip the pin before deciding whether the slug is news.
_DATED_PIN_RE = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{4})$")

NAME_TO_ID = {
    "gpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-luna": "gpt-5.6-luna",
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
    "### Standard pricing data",
    "Short context input",
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
    """A price cell to a float. The table writes money ("$12.50") and marks a
    rate that does not apply with a dash."""
    token = token.strip().strip('"').replace("$", "").replace(",", "")
    if token in {"", "-", "—", "n/a", "N/A"}:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _standard_rows_blob(md: str) -> str:
    """The rows of the STANDARD text-pricing table.

    The docs moved from a JS ``rows={[...]}`` array to a Markdown table under a
    ``### Standard pricing data`` heading (developers.openai.com, 2026-09).
    Anchored on that heading and read to the end of the table, so the Batch /
    Flex / Fast panes below — discounted or premium prices for the SAME model
    names — are excluded.
    """
    m = re.search(r"^###\s+Standard pricing data\s*$", md, re.MULTILINE)
    if not m:
        raise ExtractError('"### Standard pricing data" heading not found (restructure?)')
    rows: list[str] = []
    for line in md[m.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        rows.append(stripped)
    if not rows:
        raise ExtractError("standard pricing table has no rows (restructure?)")
    return "\n".join(rows)


def _table_rows(span: str) -> list[tuple[str, list[str]]]:
    """(model name, value cells) for each data row of a Markdown table, minus
    its header and separator rows."""
    out: list[tuple[str, list[str]]] = []
    for line in span.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        head = cells[0].lower()
        if head in {"model", ""} or set(cells[0]) <= {"-", ":", " "}:
            continue
        out.append((cells[0], cells[1:]))
    return out


def discover_unmapped(md: str) -> list[str]:
    """Text rows the standard pane prices that the catalog neither maps
    (``NAME_TO_ID``) nor declines (``DECLINED``) — i.e. models that exist and
    are priced but that roadmodel has never heard of. Sorted, de-duplicated."""
    span = _standard_rows_blob(md)
    found: set[str] = set()
    for name, _cells in _table_rows(span):
        canonical = _SUFFIX_RE.sub("", name).strip()
        base = _DATED_PIN_RE.sub("", canonical)
        if canonical in NAME_TO_ID or base in NAME_TO_ID:
            continue
        if canonical in DECLINED or base in DECLINED:
            continue
        found.add(canonical)
    return sorted(found)


def parse_pricing(md: str) -> list[dict[str, object]]:
    span = _standard_rows_blob(md)
    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for name, cells in _table_rows(span):
        canonical = _SUFFIX_RE.sub("", name).strip()
        mid = NAME_TO_ID.get(canonical)
        if mid is None or mid in seen:
            continue
        # Short-context columns: input, cached input, cache writes, output.
        # The long-context columns that follow price the same model above the
        # context threshold and are not what the catalog quotes.
        if len(cells) < 4:
            continue
        in_price = _num(cells[0])
        cache_price = _num(cells[1])
        out_price = _num(cells[3])
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

    unexpected = discover_unmapped(md)
    if unexpected:
        print(
            "extract_openai_catalog: DISCOVERY — the standard pane prices "
            f"model(s) the catalog does not carry: {unexpected}. They are "
            "reported in unexpected_slugs for the catalog cron to add or "
            "decline (do NOT ignore: this is how a new OpenAI model reaches "
            "the catalog when Cursor has not listed it).",
            file=sys.stderr,
        )

    facts = canonical_facts(models)
    return {
        "_comment": (
            "Canonical OpenAI catalog (pricing) facts extracted from the official OpenAI "
            "API pricing docs (standard pane). Generated by update/extract_openai_catalog.py "
            "— do not hand-edit; refresh by running that script. Pricing facts only; tier "
            "ratings + benchmarks are the catalog cron's lane. The Codex variants "
            "(gpt-5.3-codex / gpt-5.1-codex) have no clean provider-direct USD price "
            "(OpenAI prices Codex in credits against base models), so they stay "
            "Cursor-sourced by design. "
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
        "unexpected_slugs": unexpected,
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
