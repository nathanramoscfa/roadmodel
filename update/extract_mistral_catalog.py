"""Drift-check Mistral's committed catalog snapshot against the live pricing page.

Phase 4.6 T5. UNLIKE the other provider-direct catalog sources (DeepSeek/Anthropic/
OpenAI/Google/xAI), this is NOT a price extractor. Mistral publishes no
machine-readable price source: both ``mistral.ai/pricing`` and
``docs.mistral.ai/.../pricing`` are JS-rendered SPAs whose prices appear only as
scattered, self-conflicting hydrated text (no static table, no JSON island). Per
the T5 decision, ``update/catalog-mistral.json`` is MANUALLY maintained (prices
verified by hand from the rendered page) and this script's job is narrow but real:

  1. confirm every committed Mistral model NAME still appears on the live pricing
     page — a vanished name means a delisting/rename that needs manual attention
     (exit 4), the silent-drift failure mode the federation exists to catch;
  2. recompute the canonical facts-hash over the committed snapshot and warn if it
     no longer matches the stored ``section_sha256`` — catches a hand-edit that
     changed prices without re-stamping the hash.

It deliberately does NOT parse prices and does NOT rewrite the snapshot (so the
daily cron, which runs it fail-open, never clobbers the manual prices). When
Mistral ships a machine-readable price source, this should be promoted to a real
extractor mirroring ``extract_deepseek_catalog.py``.

Exit codes: 0 ok, 2 snapshot read/parse failure, 3 page fetch failure, 4 drift
(a committed model name is missing from the live page).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT = UPDATE_DIR / "catalog-mistral.json"

DOCS_URL = "https://mistral.ai/pricing"
PROVIDER = "mistral"
JURISDICTION = "eu"
FETCH_TIMEOUT = 30

# mistral.ai is a marketing SPA behind a CDN; send standard browser navigation
# headers so the public page returns 200 (mirrors the xAI catalog source's note —
# public docs, not fingerprint evasion).
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


class DriftError(RuntimeError):
    """A committed Mistral model is no longer present on the live pricing page."""


def fetch_text(url: str) -> str:
    response = requests.get(
        url, headers=_BROWSER_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
    )
    response.raise_for_status()
    return response.text


def canonical_facts(snapshot: dict[str, object]) -> str:
    """The same canonical-facts encoding the real extractors hash, so the stored
    ``section_sha256`` is comparable: provider + jurisdiction + models (sorted)."""
    return json.dumps(
        {
            "provider": snapshot.get("provider"),
            "jurisdiction": snapshot.get("jurisdiction"),
            "models": snapshot.get("models"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def names_missing_from_page(snapshot: dict[str, object], page: str) -> list[str]:
    """Committed model display names that no longer appear in the page text."""
    models = snapshot.get("models")
    if not isinstance(models, list):
        return []
    missing: list[str] = []
    for model in models:
        name = model.get("name") if isinstance(model, dict) else None
        if isinstance(name, str) and name not in page:
            missing.append(name)
    return missing


def hash_matches(snapshot: dict[str, object]) -> bool:
    stored = snapshot.get("section_sha256")
    recomputed = hashlib.sha256(canonical_facts(snapshot).encode("utf-8")).hexdigest()
    return stored == recomputed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drift-check the committed Mistral catalog snapshot."
    )
    parser.add_argument("--url", default=DOCS_URL, help="pricing page to drift-check against")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read page HTML from a local file instead of fetching (for tests)",
    )
    args = parser.parse_args()

    try:
        snapshot = json.loads(args.snapshot.read_text())
    except Exception as exc:
        print(f"extract_mistral_catalog: snapshot read/parse failed: {exc!r}", file=sys.stderr)
        return 2

    if not hash_matches(snapshot):
        print(
            "extract_mistral_catalog: WARNING committed section_sha256 does not match the "
            "snapshot facts — a manual price/model edit did not re-stamp the hash. Recompute "
            "and commit the correct hash.",
            file=sys.stderr,
        )

    try:
        page = args.input.read_text() if args.input else fetch_text(args.url)
    except Exception as exc:
        print(f"extract_mistral_catalog: page fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    missing = names_missing_from_page(snapshot, page)
    if missing:
        print(
            f"extract_mistral_catalog: DRIFT — committed model name(s) not found on "
            f"{args.url}: {missing}. A delisting/rename? Manually re-verify the Mistral "
            f"catalog snapshot (names + prices).",
            file=sys.stderr,
        )
        return 4

    names = [m["name"] for m in snapshot.get("models", []) if isinstance(m, dict) and "name" in m]
    print(
        f"extract_mistral_catalog: OK — all {len(names)} committed Mistral model(s) present on "
        f"{args.url} ({', '.join(names)}). NOTE prices are MANUALLY maintained (no machine-readable "
        f"Mistral source); re-verify them by eye when the page changes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
