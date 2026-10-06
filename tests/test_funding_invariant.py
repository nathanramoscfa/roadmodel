# tests/test_funding_invariant.py
"""The funding-invariant alarm (scripts/check_funding_invariant.py).

It must fire on an operator row that spent money outside the three operator
reasons, stay quiet on the rows the operator lane writes legitimately
(refusals, the bypass marker, a founder's own call), page through the ledger
rather than stop at one page, and print ids only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_funding_invariant", REPO / "scripts" / "check_funding_invariant.py"
)
assert _spec and _spec.loader
alarm = importlib.util.module_from_spec(_spec)
sys.modules["check_funding_invariant"] = alarm
_spec.loader.exec_module(alarm)


def row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "user_id": "u-1",
        "outcome": "ok",
        "cost_usd": "0.004",
        "cache_stats": {"funding_reason": "founder"},
    }
    base.update(kw)
    return base


@pytest.mark.parametrize("reason", ["founder", "invited", "bypass"])
def test_each_operator_reason_holds(reason: str) -> None:
    assert alarm.violation(row(cache_stats={"funding_reason": reason})) is None


def test_reason_outside_the_lane_fires() -> None:
    assert alarm.violation(row(cache_stats={"funding_reason": "drill"})) == "reason_outside_lane"


def test_spent_row_with_no_reason_fires() -> None:
    assert alarm.violation(row(cache_stats=None)) == "reason_outside_lane"
    assert alarm.violation(row(cache_stats={})) == "reason_outside_lane"


def test_anonymous_row_fires_unless_bypass() -> None:
    assert alarm.violation(row(user_id=None)) == "anonymous_non_bypass"
    assert alarm.violation(row(user_id=None, cache_stats={"funding_reason": "bypass"})) is None


@pytest.mark.parametrize(
    "outcome", ["rate_limited", "burst_dropped", "daily_cost_cap", "bypassed_rate_limit"]
)
def test_refusals_that_spent_nothing_are_not_judged(outcome: str) -> None:
    assert alarm.violation(row(outcome=outcome, cost_usd=None, cache_stats=None)) is None


def test_a_cost_without_an_ok_outcome_is_judged() -> None:
    assert alarm.violation(row(outcome="recommender_error", cache_stats=None)) is not None


def test_pagination_reads_every_page() -> None:
    total = alarm.PAGE * 2 + 7
    calls: list[tuple[int, int]] = []

    def page(_since: str, start: int, end: int) -> list[dict[str, Any]]:
        calls.append((start, end))
        return [row(id=i) for i in range(start, min(end + 1, total))]

    rows = alarm.read_operator_rows("2026-10-05T00:00:00+00:00", page)
    assert len(rows) == total
    assert calls == [(0, 999), (1000, 1999), (2000, 2999)]


def test_main_prints_ids_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    private_marker = "user-id-that-must-not-print"
    leaked = row(id=42, user_id=None, cache_stats={"funding_reason": "drill", "ip": private_marker})
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "unit-test-placeholder")
    monkeypatch.setattr(alarm, "postgrest_page", lambda *_: lambda *_a: [leaked])
    assert alarm.main([]) == 1
    out = capsys.readouterr().out
    assert "id=42" in out and "1 violations" in out
    assert private_marker not in out and "drill" not in out


def test_main_clean_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "unit-test-placeholder")
    monkeypatch.setattr(alarm, "postgrest_page", lambda *_: lambda *_a: [row()])
    assert alarm.main([]) == 0


def test_main_without_credentials_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert alarm.main([]) == 2
