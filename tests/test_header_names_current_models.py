"""The recommender's system-prompt headers must never pin a superseded model.

The selector sent to the engine drops every superseded model
(_drop_superseded), so a header rule that names one points the engine at a
model it cannot recommend. That happened: the FRONTIER ANCHOR rule named
"Opus 4.8" and "Fable 5" after both were superseded, and the cheaper engines
(GPT-5.6 Luna, Gemini 3.8 Flash) then anchored Quality on Fable 5.1, the
dearest model in the catalog, for 7-9 of 12 probes, including "help". Rules
name a family ("the newest Opus") instead, which stays true across releases.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from roadmodel.recommend import _SAAS_HEADER, _SAAS_LADDER_HEADER, _SAAS_LADDER_TABLE_HEADER

# Every model the lifecycle rule has tagged, retired ones included: a retired
# model leaves docs/catalog.json but keeps its element in the selector.
_SELECTOR = (Path(__file__).resolve().parents[1] / "docs" / "model-selector.txt").read_text()
_SUPERSEDED = sorted(
    re.search(r'\bname="([^"]+)"', m)[1]  # type: ignore[index]
    for m in re.findall(r"<model\s[^>]*?/>", _SELECTOR, re.S)
    if "superseded-by=" in m
)


@pytest.mark.parametrize(
    "header",
    [_SAAS_HEADER, _SAAS_LADDER_HEADER, _SAAS_LADDER_TABLE_HEADER],
    ids=["single", "ladder", "ladder-table"],
)
def test_headers_name_no_superseded_model(header: str) -> None:
    named = [
        name
        for name in _SUPERSEDED
        # A whole-name match: "Fable 5" must not match inside "Fable 5.1".
        if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.]*\d)", header)
    ]
    assert named == [], f"header pins superseded model(s): {named}"


def test_the_catalog_has_superseded_models_to_check() -> None:
    # Guards the guard: an empty list would pass vacuously.
    assert "Opus 4.8" in _SUPERSEDED
