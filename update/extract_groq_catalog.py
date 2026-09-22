"""Maintain + drift-check the Groq-hosted gpt-oss catalog snapshot.

A provider-direct catalog source for the Phase 4.6 federation, but a SPECIAL CASE:
the models are OpenAI's OPEN-WEIGHT ``gpt-oss`` family (Apache-2.0), which OpenAI
does not sell on a first-party priced API — their price is a function of the HOST.
roadmodel pins ONE host, **Groq**, as the canonical price + access platform
(``price = f(model, platform)`` with platform = Groq). The "provider" in this
snapshot is therefore the host (``groq``, us-jurisdiction), not OpenAI.

Like Mistral, Groq publishes no cleanly machine-readable price source: the
``groq.com/pricing`` page is a div-grid with hashed CSS-module class names (no
semantic table, no JSON island), so scraping prices would be brittle. Per the same
T5 decision used for Mistral, the prices in ``catalog-groq.json`` are MANUALLY
verified from the rendered page and maintained in the ``MODELS`` constant below;
this script's jobs are:

  1. deterministically (re)write ``update/catalog-groq.json`` from ``MODELS`` with a
     correct ``section_sha256`` (so the manual prices never drift from their hash);
  2. drift-check that every committed model still appears on Groq's live model
     docs (a vanished model means a delisting/rename needing manual attention —
     exit 4), the silent-drift failure mode the federation exists to catch;
  3. report gpt-oss models the page lists that the snapshot does NOT carry, in
     ``unexpected_slugs`` — the G1 discovery contract.

The drift check reads console.groq.com/docs/models, NOT groq.com/pricing: the
pricing page is now fully client-rendered and serves a shell with no model
names at all, so name-presence there matched nothing and reported every
committed model as drifted. Prices are still read by eye from the pricing
page (``PRICE_URL``).

Model identity is matched by a NORMALIZED substring (case/space/hyphen-insensitive),
so the page's display form ("GPT OSS 120B 128k") still matches the canonical id
("gpt-oss-120b"). It deliberately does NOT parse prices off the page.

Exit codes: 0 ok, 3 page fetch failure, 4 drift (a committed model is missing from
the live page).
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
DEFAULT_OUTPUT = UPDATE_DIR / "catalog-groq.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "catalog-groq.json"

# groq.com/pricing went fully client-rendered: it now returns a 55 KB shell
# with ZERO model names, prices or JSON islands, so the name-presence drift
# check below matched nothing and reported BOTH committed models as drifted —
# a permanent false positive that also made a real delisting undetectable.
# console.groq.com/docs/models is server-rendered and carries the model ids.
DOCS_URL = "https://console.groq.com/docs/models"
PRICE_URL = "https://groq.com/pricing"  # where the manual prices are read by eye
PROVIDER = "groq"
JURISDICTION = "us"
PRICES_VERIFIED_DATE = "2026-06-21"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Manually verified from https://groq.com/pricing (2026-06-21). OpenAI open-weight
# gpt-oss models hosted by Groq; $ per 1M tokens. Re-verify by eye when the page
# changes (the drift-check below only confirms NAME presence, not price).
MODELS: list[dict[str, object]] = [
    {
        "id": "gpt-oss-120b",
        "slug": "gpt-oss-120b",
        "name": "gpt-oss-120b",
        "input_price_per_1m": 0.15,
        "output_price_per_1m": 0.60,
        "cache_read_per_1m": None,
        "context_tokens": 131072,
    },
    {
        "id": "gpt-oss-20b",
        "slug": "gpt-oss-20b",
        "name": "gpt-oss-20b",
        "input_price_per_1m": 0.075,
        "output_price_per_1m": 0.30,
        "cache_read_per_1m": None,
        "context_tokens": 131072,
    },
]


# Groq hosts many open-weight families; roadmodel pins it ONLY as the host of
# OpenAI's gpt-oss models, so discovery is scoped to that family. Anything else
# on the page (Llama, Qwen, Kimi) is out of catalog scope by design, not a miss.
# Anchored on the family's naming convention — a gpt-oss id always ends in its
# parameter count ("-120b", "-20b"). Without that anchor the docs page's own
# section ids ("openai/gpt-oss-120b-limits", "…-price") match too, and a
# discovery flag that fires on anchors is a flag nobody reads.
FAMILY_RE = re.compile(r"\b(?:openai/)?(gpt-oss(?:-[a-z0-9.]+)*?-\d+b)\b", re.IGNORECASE)

# Deliberately NOT catalogued, with the reason. A slug that is neither promoted
# nor declined re-flags every run and trains the reader to ignore the flag.
DECLINED: dict[str, str] = {
    "gpt-oss-safeguard-20b": (
        "safety classifier for content moderation, not a coding/agentic model — "
        "outside the catalog's scope. Promote it by deleting this entry."
    ),
}


class DriftError(RuntimeError):
    """A committed gpt-oss model is no longer present on the live pricing page."""


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def canonical_facts(models: list[dict[str, object]]) -> str:
    return json.dumps(
        {"provider": PROVIDER, "jurisdiction": JURISDICTION, "models": models},
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(unexpected: list[str] | None = None) -> dict[str, object]:
    facts = canonical_facts(MODELS)
    return {
        "_comment": (
            "Canonical Groq-hosted gpt-oss catalog (pricing) facts. MANUALLY MAINTAINED "
            "— Groq's pricing page is a hashed-CSS div-grid with no machine-readable "
            "table, so prices in the MODELS constant of update/extract_groq_catalog.py "
            "are verified by hand from groq.com/pricing; running that script re-writes "
            "this file (with a correct section_sha256), drift-checks that the model "
            "names still appear on console.groq.com/docs/models, and reports gpt-oss "
            "models that page lists but this snapshot lacks in unexpected_slugs (it "
            "does NOT parse prices; groq.com/pricing is client-rendered and carries no "
            "model names, which is why the check reads the docs page). The models "
            "are OpenAI's open-weight gpt-oss (Apache-2.0); Groq is the pinned host that "
            "defines price + the groq-api access method (price = f(model, platform)). "
            "Consumed OFFLINE by update/merge_catalog.py + "
            "update/validate_catalog_conformance.py. overlay_mode whole-element: not on "
            "Cursor's page, so the cron's Opus pass drops these and the de-clobber "
            "overlay re-adds them from the committed selector."
        ),
        "price_maintenance": "manual",
        "prices_verified_date": PRICES_VERIFIED_DATE,
        "source_url": DOCS_URL,
        "provider": PROVIDER,
        "jurisdiction": JURISDICTION,
        "overlay_mode": "whole-element",
        "models": MODELS,
        "slug_to_id": {str(m["slug"]): str(m["id"]) for m in MODELS},
        "unexpected_slugs": list(unexpected or []),
        "missing_on_page": [],
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def _normalize(text: str) -> str:
    """Lowercase + strip every non-alphanumeric char.

    So the page's "GPT OSS 120B 128k" and the canonical id "gpt-oss-120b" both
    normalize to a form where ``gptoss120b`` is a substring — robust to spacing,
    hyphenation, and casing differences between the marketing page and our ids.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def names_missing_from_page(page: str) -> list[str]:
    norm_page = _normalize(page)
    return [str(m["id"]) for m in MODELS if _normalize(str(m["id"])) not in norm_page]


def unexpected_on_page(page: str) -> list[str]:
    """gpt-oss models the page carries that the snapshot does not — the G1
    discovery contract, so a new family member cannot sit unnoticed behind a
    price source nobody re-reads."""
    known = {_normalize(str(m["id"])) for m in MODELS}
    declined = {_normalize(name) for name in DECLINED}
    found: dict[str, None] = {}
    for raw in FAMILY_RE.findall(page):
        slug = raw.lower()
        norm = _normalize(slug)
        if norm not in known and norm not in declined:
            found[slug] = None
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="(Re)write + drift-check the Groq-hosted gpt-oss catalog snapshot."
    )
    parser.add_argument("--url", default=DOCS_URL, help="pricing page to drift-check against")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read page HTML from a local file instead of fetching (for tests)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="where to write the JSON snapshot (default: committed canonical copy)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="write the snapshot but skip the live-page drift check (offline use)",
    )
    args = parser.parse_args()

    # Read the page FIRST when we are going to: discovery belongs in the
    # snapshot, and a fetch failure must not leave a half-truth on disk.
    page: str | None = None
    if not args.no_verify:
        try:
            page = args.input.read_text() if args.input else fetch_text(args.url)
        except Exception as exc:
            print(f"extract_groq_catalog: page fetch/read failed: {exc!r}", file=sys.stderr)
            return 3

    # Always (re)write the snapshot from the manual constant — deterministic, with a
    # correct hash. Byte-stable when the constant and the discovery set are unchanged.
    unexpected = unexpected_on_page(page) if page is not None else []
    snapshot = build_snapshot(unexpected)
    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)
    summary = ", ".join(str(m["id"]) for m in MODELS)
    print(f"extract_groq_catalog: wrote {args.output} ({summary})")

    if page is None:
        return 0

    if unexpected:
        print(
            f"extract_groq_catalog: DISCOVERY — {args.url} lists gpt-oss model(s) the "
            f"catalog does not carry: {unexpected}. They are reported in "
            f"unexpected_slugs for the catalog cron to add or decline."
        )

    missing = names_missing_from_page(page)
    if missing:
        print(
            f"extract_groq_catalog: DRIFT — committed model(s) not found on {args.url}: "
            f"{missing}. A delisting/rename? Manually re-verify the Groq gpt-oss snapshot "
            f"(names + prices in the MODELS constant).",
            file=sys.stderr,
        )
        return 4

    print(
        f"extract_groq_catalog: OK — all {len(MODELS)} committed gpt-oss model(s) present "
        f"on {args.url}. NOTE prices are MANUALLY maintained (Groq has no machine-readable "
        f"price source); re-verify them by eye when the page changes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
