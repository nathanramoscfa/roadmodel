"""Tests for the editorial Annual-column carry-forward (issue #315).

`update/update_models.py::carry_forward_annual_column` deterministically restores
the committed Subscription Tiers `Annual` cells after the Opus cost-scale pass, so
the cron can never originate an annual price (a plausibly-shaped hallucination is
indistinguishable from a real capture by the old 8x-12x guard). A tier new to the
table is nulled to `—` and flagged for maintainer review.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"


def _load() -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        return importlib.reload(importlib.import_module("update_models"))
    finally:
        sys.path.pop(0)


# A faithful slice: a per-token price table (must be untouched) + the Subscription
# Tiers table the overlay operates on.
def _doc(cursor_ultra_annual: str, *, extra_row: str = "") -> str:
    rows = (
        "| Subscription  | Monthly | Annual | Provider  | Access methods unlocked | Coverage     |\n"
        "| ------------- | ------- | ------ | --------- | ----------------------- | ------------ |\n"
        "| Claude Pro    | $20     | $200   | Anthropic | claude-code, claude-web | Claude tier. |\n"
        f"| Cursor Ultra  | $200    | {cursor_ultra_annual:<6} | Cursor    | cursor                  | Ultra tier.  |\n"
    )
    return (
        "## Per-token pricing\n\n"
        "| Model         | Input | Cache Write | Cache Read | Output | Tier | Notes |\n"
        "| ------------- | ----- | ----------- | ---------- | ------ | ---- | ----- |\n"
        "| Claude Opus 5 | $5    | $6          | $0.50      | $25    | S    | —     |\n\n"
        "## Subscription Tiers and Access Methods\n\n"
        f"{rows}{extra_row}\n"
        "Some trailing prose.\n"
    )


def test_parse_subscription_annuals_reads_only_the_subscription_table() -> None:
    mod = _load()
    annuals = mod.parse_subscription_annuals(_doc("—"))
    assert annuals == {"Claude Pro": "$200", "Cursor Ultra": "—"}
    # The per-token price table's "Claude Opus 5" row is NOT a subscription tier.
    assert "Claude Opus 5" not in annuals


def test_unchanged_annuals_are_a_byte_stable_noop() -> None:
    mod = _load()
    before = _doc("—")
    after = _doc("—")  # Opus left the annual verbatim
    result, warnings = mod.carry_forward_annual_column(before, after)
    assert result == after
    assert warnings == []


def test_cron_changed_existing_annual_is_restored() -> None:
    mod = _load()
    before = _doc("—")  # committed editorial value
    after = _doc("$1920")  # Opus invented a plausibly-shaped annual
    result, warnings = mod.carry_forward_annual_column(before, after)
    # Restored to the committed `—`.
    assert mod.parse_subscription_annuals(result)["Cursor Ultra"] == "—"
    assert "$1920" not in result
    assert len(warnings) == 1
    assert "Cursor Ultra" in warnings[0] and "$1920" in warnings[0]


def test_committed_annual_survives_a_blanking_cron() -> None:
    mod = _load()
    before = _doc("$1920")  # a maintainer-verified editorial annual
    after = _doc("—")  # Opus dropped it
    result, warnings = mod.carry_forward_annual_column(before, after)
    assert mod.parse_subscription_annuals(result)["Cursor Ultra"] == "$1920"
    assert len(warnings) == 1


def test_new_tier_annual_is_nulled_and_flagged() -> None:
    mod = _load()
    before = _doc("—")
    new_row = "| New Plan      | $60     | $576   | Cursor    | cursor                  | New tier.    |\n"
    after = _doc("—", extra_row=new_row)
    result, warnings = mod.carry_forward_annual_column(before, after)
    assert mod.parse_subscription_annuals(result)["New Plan"] == "—"
    assert "$576" not in result
    assert len(warnings) == 1
    assert "NEW tier" in warnings[0] and "New Plan" in warnings[0]


def test_new_tier_already_null_is_silent() -> None:
    mod = _load()
    before = _doc("—")
    new_row = "| New Plan      | $60     | —      | Cursor    | cursor                  | New tier.    |\n"
    after = _doc("—", extra_row=new_row)
    result, warnings = mod.carry_forward_annual_column(before, after)
    assert warnings == []


def test_missing_subscription_table_is_a_noop() -> None:
    mod = _load()
    text = "## Per-token pricing\n\nNo subscription table here.\n"
    result, warnings = mod.carry_forward_annual_column(text, text)
    assert result == text
    assert warnings == []
