"""scripts/collect_claude_usage.py: strict parse of the headless `claude -p /usage` meters."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_claude_usage as ccu
from pool_table import render
from pool_usage import decide

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 23, 0, 5, tzinfo=NY).timestamp()
USAGE = """You are currently using your subscription to power your Claude Code usage

Current session: 16% used · resets Oct 23 at 3:40am (America/New_York)
Current week (all models): 46% used · resets Oct 27 at 8pm (America/New_York)
Current week (Fable): 0% used · resets Oct 27 at 8pm (America/New_York)

What's contributing to your limits usage?
"""


def at(*args: int) -> float:
    return datetime(*args, tzinfo=NY).timestamp()


def test_parses_real_output_into_three_windows() -> None:
    snap = ccu.parse(USAGE, NOW)
    assert snap is not None and snap["source"] == "claude" and snap["observed_at"] == NOW
    by = {w["name"]: w for w in snap["windows"]}
    assert by["5h"]["used_percent"] == 16 and by["5h"]["resets_at"] == at(2026, 10, 23, 3, 40)
    assert by["weekly"]["used_percent"] == 46 and by["weekly"]["window_minutes"] == 10080
    assert by["weekly"]["resets_at"] == at(2026, 10, 27, 20)
    assert by["fable"]["used_percent"] == 0


def test_time_only_reset_is_the_next_such_moment() -> None:
    assert ccu.parse_reset("3:40am", "America/New_York", NOW) == at(2026, 10, 23, 3, 40)
    assert ccu.parse_reset("12am", "America/New_York", NOW) == at(2026, 10, 24, 0)
    assert ccu.parse_reset("12pm", "America/New_York", NOW) == at(2026, 10, 23, 12)


def test_year_rolls_over_for_a_january_reset() -> None:
    now = at(2026, 12, 30, 12)
    assert ccu.parse_reset("Jan 2 at 8pm", "America/New_York", now) == at(2027, 1, 2, 20)


def test_unexpected_output_saves_nothing() -> None:
    assert ccu.parse("", NOW) is None
    assert ccu.parse("Usage is unavailable right now", NOW) is None
    # Missing the all-models weekly line: no pool to describe, even with a session line.
    assert ccu.parse(USAGE.replace("(all models)", "(some models)"), NOW) is None
    # An unreadable reset drops that window only.
    bad = USAGE.replace("Oct 23 at 3:40am", "someday")
    snap = ccu.parse(bad, NOW)
    assert snap is not None and {w["name"] for w in snap["windows"]} == {"weekly", "fable"}


def test_unknown_zone_is_rejected() -> None:
    assert ccu.parse_reset("8pm", "Mars/Olympus", NOW) is None


TABLE = """## Usage-pool status

| Pool | Window | State | Resets (local time) | Notes |
| ---- | ------ | ----- | ------------------- | ----- |
| claude.ai Max — weekly (all models) | 7 days | `tight` | Tue 2026-10-13 20:00 EDT | old. |
| claude.ai Max — 5-hour session | 5 hours | `headroom` | rolling | old. |
| claude.ai Max — Fable sub-cap | 7 days | `headroom` | Tue 2026-10-13 20:00 EDT | manual. |
"""


def test_fable_row_is_updated_automatically() -> None:
    snap = ccu.parse(USAGE.replace("Fable): 0%", "Fable): 98%"), NOW)
    assert snap is not None
    out = render(TABLE, {"claude": snap}, NOW + 60)
    fable = next(line for line in out.splitlines() if "Fable" in line)
    assert "`exhausted`" in fable and "[auto: claude 98%" in fable
    weekly = next(line for line in out.splitlines() if "all models" in line)
    # 46% used with ~31% of the week gone projects past 100% at reset: tight by pace.
    assert "`tight`" in weekly and "46%" in weekly


def test_fresh_fable_reading_decides_like_any_weekly_window() -> None:
    snap = ccu.parse(USAGE, NOW)
    assert snap is not None
    fable = next(w for w in snap["windows"] if w["name"] == "fable")
    assert decide(snap, fable, NOW + 60) == "headroom"


def test_cold_cli_cost_summary_is_retried(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    outputs = ["Total cost: $0.0000\n", USAGE]
    calls: list[dict[str, str]] = []

    def run(argv, **kw):  # type: ignore[no-untyped-def]
        calls.append(kw["env"])
        return type("R", (), {"returncode": 0, "stdout": outputs[len(calls) - 1]})()

    monkeypatch.setattr(ccu, "find_claude", lambda: "/x/claude")
    monkeypatch.setattr(ccu.subprocess, "run", run)
    monkeypatch.setattr(ccu.time, "sleep", lambda _s: None)
    snap = ccu.collect(NOW, Path("/"))
    assert snap is not None and len(calls) == 2
    assert set(calls[0]) == {"HOME", "USER", "PATH"}  # no tokens or session ids leak in


def test_missing_cli_or_persistent_garbage_saves_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ccu, "find_claude", lambda: None)
    assert ccu.collect(NOW, Path("/")) is None
