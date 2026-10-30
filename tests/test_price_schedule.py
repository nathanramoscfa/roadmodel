"""A list price the provider announces in advance is read for the day.

Google prices Gemini 4 Argon at $2/$10 "through November 30, 2026" and $4/$20
"starting December 1, 2026". The Google extractor reads the price in effect
on the day it runs and records the later one in its snapshot's
``price_schedule``, so the daily catalog refresh moves to $4/$20 on December 1
even if the page still quotes both (2026-10-30). The catalog itself carries no
schedule: build_catalog is a reviewed validator and the typed catalog gate
admits prices, letters and prose only.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

UPDATE_DIR = Path(__file__).resolve().parents[1] / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import extract_google_catalog as google  # noqa: E402

ARGON_ROWS = [
    ["", "Free Tier", "Paid Tier, per 1M tokens in USD"],
    [
        "Input price",
        "Not available",
        "$2.00 through November 30, 2026. $4.00 starting December 1, 2026.",
    ],
    [
        "Output price (including thinking tokens)",
        "Not available",
        "$10.00 through November 30, 2026. $20.00 starting December 1, 2026.",
    ],
]


def test_the_extractor_reads_todays_price_and_the_announced_one() -> None:
    before = google._paid_prices(ARGON_ROWS, date(2026, 10, 30))
    assert before == (
        2.0,
        10.0,
        [{"from": "2026-12-01", "input_price_per_1m": 4.0, "output_price_per_1m": 20.0}],
    )
    # On the day, the later price is today's and nothing is left to announce.
    assert google._paid_prices(ARGON_ROWS, date(2026, 12, 1)) == (4.0, 20.0, [])
    # A plain cell has no schedule.
    plain = [["Input price", "x", "$0.30"], ["Output price", "x", "$2.50"]]
    assert google._paid_prices(plain, date(2026, 10, 30)) == (0.3, 2.5, [])


def test_the_snapshot_records_argons_announced_price() -> None:
    import json

    snap = json.loads((UPDATE_DIR / "catalog-google.json").read_text())
    argon = next(m for m in snap["models"] if m["id"] == "gemini-4-argon")
    assert argon["price_schedule"] == [
        {"from": "2026-12-01", "input_price_per_1m": 4.0, "output_price_per_1m": 20.0}
    ]
