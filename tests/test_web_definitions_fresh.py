"""Anti-staleness guard for the /models tooltip + legend copy.

Every hover definition on /models is read by someone deciding which model to
run, so a figure baked into that prose is a wrong answer the moment the daily
crons move the data. The rule: anything that CHANGES with the data — the
Artificial Analysis snapshot date, how many models are measured, how many
evaluations the index spans, the index version, the derivation bands, the
evidence benchmark per category — is rendered from the data at request time
(``SortHeader``'s ``detail`` prop, the legend's ``DERIVATION_BANDS`` /
``CATEGORY_FIGURE`` constants, the table footer), never typed into a string.

These tests fail when a stale-prone literal is typed into a definition, and
when the live derivations are removed from the components that render them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "web"

DEFINITION_SOURCES = (
    WEB / "lib" / "catalog-fields.ts",
    WEB / "lib" / "benchmark-grid.ts",
    WEB / "lib" / "glossary.ts",
)

# `definition: "…"` / `definition:\n  "…"` — the hover text itself.
_DEFINITION_RE = re.compile(r'definition:\s*\n?\s*"((?:[^"\\]|\\.)*)"', re.S)

# Literals that go stale when the data refreshes:
#   - an index / benchmark VERSION ("v4.3") — AA renumbers and scores across
#     versions are not comparable;
#   - a YEAR — a "verified 2026-06-15" style claim rots silently;
#   - an inventory COUNT ("ten evaluations", "46 models measured").
_STALE_RE = re.compile(
    r"""
    \bv\d+\.\d+\b
    | \b20(?:2[4-9]|3\d)\b
    | \b\d+\s+(?:evaluations|benchmarks|catalog\ models|models\ measured)\b
    | \b(?:ten|eleven|twelve|thirteen|fourteen|fifteen)\s+(?:evaluations|benchmarks)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@pytest.mark.parametrize("source", DEFINITION_SOURCES, ids=lambda p: p.name)
def test_definitions_carry_no_stale_prone_literals(source: Path) -> None:
    text = source.read_text(encoding="utf-8")
    offenders: list[str] = []
    for match in _DEFINITION_RE.finditer(text):
        body = match.group(1)
        hit = _STALE_RE.search(body)
        if hit:
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{source.relative_to(REPO_ROOT)}:{line}: {hit.group(0)!r}")
    assert not offenders, (
        "A /models definition hardcodes a value that the daily refresh changes. "
        "Render it from the data instead (SortHeader `detail`, DERIVATION_BANDS, "
        "CATEGORY_FIGURE, the table footer):\n  " + "\n  ".join(offenders)
    )


def test_headers_render_their_live_statistics() -> None:
    """The two numeric columns state their own provenance from the data: Score
    from the fit it just computed, AA Index from the snapshot it just read."""
    catalog = (WEB / "components" / "ModelCatalog.tsx").read_text(encoding="utf-8")
    assert "scoreFit.n" in catalog and "scoreFit.slope" in catalog and "scoreFit.sigma" in catalog
    assert "Fit over ${scoreFit.n} measured models" in catalog
    assert "${benchmarksGeneratedAt}" in catalog
    assert "${measuredCount} of ${models.length} catalog models measured" in catalog


def test_legend_derives_the_bands_and_evidence_names() -> None:
    legend = (WEB / "components" / "CatalogLegend.tsx").read_text(encoding="utf-8")
    assert "DERIVATION_BANDS.map" in legend, "band rule must come from the constant"
    assert "CATEGORY_FIGURE" in legend, "evidence benchmark names must come from the mapping"
    assert "{BAND_RULE}" in legend and "{DERIVED_EVIDENCE}" in legend
    # The pre-#649 hardcoded forms must not come back.
    assert "S within 5 points" not in legend
    assert "Terminal-Bench 2.1" not in legend
