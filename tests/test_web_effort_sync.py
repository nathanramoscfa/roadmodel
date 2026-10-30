"""The web reads a pick's facts at its effort the way the scorer does.

web/lib/pick-effort.ts places a model at each effort on the frontier at its
blended list price times the effort's token multiplier, as
scoring.frontier_price does; the two multiplier tables must agree.
"""

from __future__ import annotations

import re
from pathlib import Path

from roadmodel import scoring

PICK_EFFORT = Path(__file__).resolve().parents[1] / "web" / "lib" / "pick-effort.ts"


def test_the_web_effort_multipliers_match_the_scorer() -> None:
    text = PICK_EFFORT.read_text(encoding="utf-8")
    block = re.search(r"EFFORT_TOKEN_MULTIPLIER = \{(.*?)\}", text, re.S)
    assert block is not None
    web = {k: float(v) for k, v in re.findall(r"(\w+):\s*([\d.]+)", block.group(1))}
    assert web == scoring.EFFORT_TOKEN_MULTIPLIER


def test_the_web_prices_an_effort_as_the_scorer_does() -> None:
    """Only the output part of the blended price scales with the effort's
    tokens (scoring.effort_price, 2026-10-30)."""
    text = PICK_EFFORT.read_text(encoding="utf-8")
    body = re.search(r"export function effortPrice\(.*?\n\}", text, re.S)
    assert body is not None
    assert "3 * row.input_price_per_1m" in body.group(0)
    assert "row.output_price_per_1m * tokenMultiplier(row, level)" in body.group(0)
    assert "/ 4" in body.group(0)
    assert "blended * tokenMultiplier" not in text
