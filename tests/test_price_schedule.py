"""A list price the provider announces in advance takes effect on its date.

Google prices Gemini 4 Argon at $2/$10 "through November 30, 2026" and $4/$20
"starting December 1, 2026". The Google extractor reads both, the catalog
carries the later one (``price-from`` on the selector, ``price_schedule`` in
catalog.json), and roadmodel's catalog loader applies it from its date, so the
step-up needs no release (2026-10-30).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

from roadmodel import cost

UPDATE_DIR = Path(__file__).resolve().parents[1] / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import build_catalog  # noqa: E402
import extract_google_catalog as google  # noqa: E402
import merge_catalog  # noqa: E402

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


ELEMENT = (
    '<model id="gemini-4-argon" name="Gemini 4 Argon"\n'
    '             input-price-per-1m="$2.00" output-price-per-1m="$10.00"\n'
    '             jurisdiction="us"/>'
)


def _snapshot(schedule: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    model: dict[str, Any] = {
        "id": "gemini-4-argon",
        "input_price_per_1m": 2.0,
        "output_price_per_1m": 10.0,
    }
    if schedule is not None:
        model["price_schedule"] = schedule
    return [{"models": [model]}]


def test_the_overlay_writes_updates_and_drops_price_from() -> None:
    later = [{"from": "2026-12-01", "input_price_per_1m": 4.0, "output_price_per_1m": 20.0}]
    snaps = _snapshot(later)
    prices = merge_catalog.snapshot_price_map(snaps)
    schedules = merge_catalog.snapshot_schedule_map(snaps)
    assert schedules == {"gemini-4-argon": "2026-12-01 $4.00/$20.00"}
    new, applied, flags = merge_catalog.apply_price_overlay(ELEMENT, prices, schedules)
    assert (applied, flags) == (["gemini-4-argon"], [])
    assert 'output-price-per-1m="$10.00" price-from="2026-12-01 $4.00/$20.00"' in new
    # Idempotent; a changed schedule replaces it; none removes it.
    assert merge_catalog.apply_price_overlay(new, prices, schedules)[1] == []
    moved = merge_catalog.snapshot_schedule_map(_snapshot([{**later[0], "from": "2027-01-01"}]))
    assert (
        'price-from="2027-01-01 $4.00/$20.00"'
        in merge_catalog.apply_price_overlay(new, prices, moved)[0]
    )
    gone = merge_catalog.snapshot_schedule_map(_snapshot(None))
    assert merge_catalog.apply_price_overlay(new, prices, gone)[0] == ELEMENT
    # Without schedules the overlay leaves the attribute alone.
    assert merge_catalog.apply_price_overlay(new, prices)[0] == new


def test_the_catalog_carries_the_schedule() -> None:
    assert build_catalog._price_schedule("2026-12-01 $4.00/$20.00") == {
        "price_schedule": [
            {"from": "2026-12-01", "input_price_per_1m": 4.0, "output_price_per_1m": 20.0}
        ]
    }
    assert build_catalog._price_schedule("") == {}


def test_the_loader_applies_a_scheduled_price_from_its_date() -> None:
    def catalog() -> dict[str, Any]:
        return {
            "models": [
                {
                    "id": "gemini-4-argon",
                    "input_price_per_1m": 2.0,
                    "output_price_per_1m": 10.0,
                    "price_schedule": [
                        {
                            "from": "2026-12-01",
                            "input_price_per_1m": 4.0,
                            "output_price_per_1m": 20.0,
                        }
                    ],
                },
                {"id": "plain", "input_price_per_1m": 1.0, "output_price_per_1m": 5.0},
            ]
        }

    before = cost.apply_price_schedule(catalog(), date(2026, 11, 30))["models"]
    assert (before[0]["input_price_per_1m"], before[0]["output_price_per_1m"]) == (2.0, 10.0)
    after = cost.apply_price_schedule(catalog(), date(2026, 12, 1))["models"]
    assert (after[0]["input_price_per_1m"], after[0]["output_price_per_1m"]) == (4.0, 20.0)
    assert after[1]["input_price_per_1m"] == 1.0


def test_the_bundled_catalog_announces_argons_december_price() -> None:
    argon = next(m for m in cost._load_catalog()["models"] if m["id"] == "gemini-4-argon")
    schedule = argon.get("price_schedule")
    assert schedule == [
        {"from": "2026-12-01", "input_price_per_1m": 4.0, "output_price_per_1m": 20.0}
    ]
