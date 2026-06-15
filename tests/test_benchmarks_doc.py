"""Consistency guard for docs/benchmarks-and-ratings.md.

The web glossary (web/lib/glossary.ts) is the source of truth for the benchmark
names + their links (it powers the rationale's clickable terms). This doc, the
README, and the in-app docs page must list the same set, so a test pins it: every
glossary benchmark term + URL must appear in the doc. Mirrors the regex-parsing
approach in test_doc_schema.py (no JS runtime needed).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = REPO_ROOT / "web" / "lib" / "glossary.ts"
DOC = REPO_ROOT / "docs" / "benchmarks-and-ratings.md"


def _benchmark_entries() -> list[tuple[str, str]]:
    """Return (term, url) for each glossary entry that has a url (the benchmarks).

    A url belongs to the nearest preceding ``term:`` (entries list term before url),
    so tier entries (no url) are naturally excluded.
    """
    text = GLOSSARY.read_text(encoding="utf-8")
    terms = [(m.start(), m.group(1)) for m in re.finditer(r'term:\s*"([^"]+)"', text)]
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'url:\s*"([^"]+)"', text):
        prior = [term for pos, term in terms if pos < m.start()]
        if prior:
            out.append((prior[-1], m.group(1)))
    return out


def test_glossary_exposes_benchmark_urls() -> None:
    entries = _benchmark_entries()
    assert len(entries) >= 13, f"expected ~13 benchmark urls in the glossary, found {len(entries)}"


def test_doc_covers_every_benchmark_term_and_url() -> None:
    doc = DOC.read_text(encoding="utf-8")
    missing: list[str] = []
    for term, url in _benchmark_entries():
        if term not in doc:
            missing.append(f"term '{term}'")
        if url not in doc:
            missing.append(f"url '{url}' (for {term})")
    assert not missing, (
        "docs/benchmarks-and-ratings.md drifted from the web glossary — missing:\n  "
        + "\n  ".join(missing)
    )


def test_doc_documents_the_rating_scale() -> None:
    doc = DOC.read_text(encoding="utf-8")
    for rating in ("S", "A", "B", "C", "D"):
        assert f"**{rating}**" in doc, f"rating-scale row for {rating} missing from the doc"
