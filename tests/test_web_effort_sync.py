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
